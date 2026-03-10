"""
Convert MotionMillion 272-rpr .npy files to standard AMASS SMPL .npz format.

The 272-dimensional motion representation layout (for 22 joints):
  [0:2]     - root velocity on XZ plane (no heading) (2)
  [2:8]     - global heading differential rotation in 6D (6)
  [8:74]    - joint positions without heading (22×3 = 66)
  [74:140]  - joint velocities without heading (22×3 = 66)
  [140:272] - joint rotations in 6D representation (22×6 = 132)
  Total: 2 + 6 + 66 + 66 + 132 = 272

The conversion pipeline:
  1. Recover global heading rotation from accumulated 6D heading diffs
  2. Recover root translation from root velocity + heading
  3. Recover joint rotation matrices (apply heading to root joint)
  4. Convert rotation matrices to axis-angle (SMPL format)
  5. Save as standard AMASS SMPL .npz

Output AMASS SMPL .npz format:
  - poses:            (T, 72) - axis-angle rotations, [global_orient(3), body_pose(69)]
  - trans:            (T, 3)  - root translation
  - betas:            (10,)   - body shape parameters (zeros, not available in 272rpr)
  - gender:           str     - "neutral"
  - mocap_framerate:  float   - 30.0 (MotionMillion uses 30fps)

Usage:
  # Single file:
  python convert_272rpr_to_amass_smpl.py --input <file.npy> --output <output.npz>

  # Batch convert (recursive):
  python convert_272rpr_to_amass_smpl.py --input <input_dir> --output <output_dir>

  # Batch with options:
  python convert_272rpr_to_amass_smpl.py --input <input_dir> --output <output_dir> --skip_existing --workers 4
"""

import numpy as np
import torch
import torch.nn.functional as F
import os
import sys
import argparse
import time
import traceback
import logging
from multiprocessing import Pool, cpu_count
from functools import partial
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Module-level logger – logs one line per converted file (OK / FAILED)
# Call setup_logging() in main() or before batch conversion to configure it.
# ---------------------------------------------------------------------------
logger = logging.getLogger("convert_272rpr")


def setup_logging(log_level: str = "INFO", log_file: str = None):
    """
    Configure the module logger.

    Args:
        log_level: one of DEBUG / INFO / WARNING / ERROR (case-insensitive)
        log_file:  optional path to write log to a file in addition to stdout
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    fmt     = "[%(asctime)s] %(levelname)-8s %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    logger.setLevel(numeric_level)
    logger.propagate = False
    logger.handlers.clear()

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter(fmt, datefmt))
    logger.addHandler(sh)

    if log_file:
        os.makedirs(os.path.dirname(log_file) if os.path.dirname(log_file) else ".", exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter(fmt, datefmt))
        logger.addHandler(fh)


# Apply a minimal default so logger works even without calling setup_logging()
logging.basicConfig(level=logging.INFO,
                    format="[%(asctime)s] %(levelname)-8s %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")


# ============================================================================
# Rotation conversion utilities (self-contained, no external dependencies)
# ============================================================================

def rotation_6d_to_matrix(d6):
    """
    Converts 6D rotation representation to rotation matrix.
    Args:
        d6: numpy array or torch tensor of shape (*, 6)
    Returns:
        Rotation matrices of shape (*, 3, 3)
    """
    is_numpy = isinstance(d6, np.ndarray)
    if is_numpy:
        d6 = torch.from_numpy(d6).float()
    
    a1, a2 = d6[..., :3], d6[..., 3:]
    b1 = F.normalize(a1, dim=-1)
    b2 = a2 - (b1 * a2).sum(-1, keepdim=True) * b1
    b2 = F.normalize(b2, dim=-1)
    b3 = torch.cross(b1, b2, dim=-1)
    mat = torch.stack((b1, b2, b3), dim=-2)
    
    if is_numpy:
        return mat.numpy()
    return mat


def matrix_to_axis_angle(matrix):
    """
    Convert rotation matrices to axis-angle representation.
    Args:
        matrix: torch tensor of shape (*, 3, 3)
    Returns:
        Axis-angle of shape (*, 3)
    """
    is_numpy = isinstance(matrix, np.ndarray)
    if is_numpy:
        matrix = torch.from_numpy(matrix).float()
    
    quaternions = matrix_to_quaternion(matrix)
    aa = quaternion_to_axis_angle(quaternions)
    
    if is_numpy:
        return aa.numpy()
    return aa


def axis_angle_to_matrix(axis_angle):
    """
    Convert axis-angle representation to rotation matrix via Rodrigues formula.
    Args:
        axis_angle: numpy array or torch tensor of shape (*, 3)
    Returns:
        Rotation matrices of shape (*, 3, 3)
    """
    is_numpy = isinstance(axis_angle, np.ndarray)
    if is_numpy:
        axis_angle = torch.from_numpy(axis_angle).float()

    angle = torch.norm(axis_angle, dim=-1, keepdim=True)          # (*, 1)
    safe_angle = torch.where(angle > 1e-6, angle, torch.ones_like(angle))
    axis = axis_angle / safe_angle                                  # (*, 3)

    cos_a = torch.cos(angle)    # (*, 1)
    sin_a = torch.sin(angle)    # (*, 1)

    x = axis[..., 0]
    y = axis[..., 1]
    z = axis[..., 2]
    zeros = torch.zeros_like(x)

    # Skew-symmetric matrix K
    K = torch.stack([
        torch.stack([zeros,  -z,  y], dim=-1),
        torch.stack([z,  zeros, -x], dim=-1),
        torch.stack([-y,   x,  zeros], dim=-1),
    ], dim=-2)                                                       # (*, 3, 3)

    # Outer product axis ⊗ axis
    axis_outer = axis.unsqueeze(-1) * axis.unsqueeze(-2)            # (*, 3, 3)

    eye = torch.eye(3, dtype=axis_angle.dtype, device=axis_angle.device)
    eye = eye.expand(*axis_angle.shape[:-1], 3, 3)

    R = (cos_a.unsqueeze(-1) * eye
         + sin_a.unsqueeze(-1) * K
         + (1 - cos_a).unsqueeze(-1) * axis_outer)

    # Zero-angle → identity
    zero_mask = (angle < 1e-6).unsqueeze(-1)
    R = torch.where(zero_mask, eye, R)

    if is_numpy:
        return R.numpy()
    return R


# Y-up → Z-up coordinate transformation matrix
# x' = x,  y' = -z,  z' = y
_R_COORD_ZUP = np.array([[1,  0,  0],
                          [0,  0, -1],
                          [0,  1,  0]], dtype=np.float32)


def yup_to_zup(poses, trans):
    """
    Transform SMPL poses and trans from Y-up to Z-up coordinate system.

    Only global_orient (poses[:, :3]) and trans are affected.
    Body pose (poses[:, 3:]) expresses relative joint rotations in the
    local parent frame and therefore does not change.

    Transformation:  p_zup = R_coord @ p_yup
      R_global_zup = R_coord @ R_global_yup
      t_zup        = R_coord @ t_yup

    Args:
        poses: (T, 72) float32 array  [global_orient(3) + body_pose(69)]
        trans: (T, 3)  float32 array
    Returns:
        poses_new: (T, 72) float32 array in Z-up frame
        trans_new: (T, 3)  float32 array in Z-up frame
    """
    R_coord = _R_COORD_ZUP

    # --- translation ---
    trans_new = (R_coord @ trans.T).T                               # (T, 3)

    # --- global orientation ---
    global_orient_aa = poses[:, :3]                                 # (T, 3)
    R_old = axis_angle_to_matrix(global_orient_aa)                  # (T, 3, 3)
    R_new = (R_coord[None] @ R_old).astype(np.float32)             # (T, 3, 3)
    global_orient_aa_new = matrix_to_axis_angle(R_new)              # (T, 3)

    poses_new = poses.copy()
    poses_new[:, :3] = global_orient_aa_new

    return poses_new, trans_new


def matrix_to_quaternion(matrix):
    """
    Convert rotation matrices to quaternions (real part first).
    Args:
        matrix: Rotation matrices of shape (..., 3, 3).
    Returns:
        Quaternions of shape (..., 4), real part first.
    """
    if matrix.size(-1) != 3 or matrix.size(-2) != 3:
        raise ValueError(f"Invalid rotation matrix shape {matrix.shape}.")
    
    batch_dim = matrix.shape[:-2]
    
    m00, m01, m02 = matrix[..., 0, 0], matrix[..., 0, 1], matrix[..., 0, 2]
    m10, m11, m12 = matrix[..., 1, 0], matrix[..., 1, 1], matrix[..., 1, 2]
    m20, m21, m22 = matrix[..., 2, 0], matrix[..., 2, 1], matrix[..., 2, 2]
    
    def _sqrt_positive_part(x):
        ret = torch.zeros_like(x)
        positive_mask = x > 0
        ret[positive_mask] = torch.sqrt(x[positive_mask])
        return ret
    
    def _copysign(a, b):
        signs_differ = (a < 0) != (b < 0)
        return torch.where(signs_differ, -a, a)
    
    o0 = 0.5 * _sqrt_positive_part(1 + m00 + m11 + m22)
    x = 0.5 * _sqrt_positive_part(1 + m00 - m11 - m22)
    y = 0.5 * _sqrt_positive_part(1 - m00 + m11 - m22)
    z = 0.5 * _sqrt_positive_part(1 - m00 - m11 + m22)
    o1 = _copysign(x, m21 - m12)
    o2 = _copysign(y, m02 - m20)
    o3 = _copysign(z, m10 - m01)
    
    return torch.stack((o0, o1, o2, o3), -1)


def quaternion_to_axis_angle(quaternions):
    """
    Convert quaternions (real part first) to axis-angle.
    Args:
        quaternions: tensor of shape (..., 4)
    Returns:
        Axis-angle of shape (..., 3)
    """
    norms = torch.norm(quaternions[..., 1:], p=2, dim=-1, keepdim=True)
    half_angles = torch.atan2(norms, quaternions[..., :1])
    angles = 2 * half_angles
    eps = 1e-6
    small_angles = angles.abs() < eps
    sin_half_angles_over_angles = torch.empty_like(angles)
    sin_half_angles_over_angles[~small_angles] = (
        torch.sin(half_angles[~small_angles]) / angles[~small_angles]
    )
    sin_half_angles_over_angles[small_angles] = (
        0.5 - (angles[small_angles] * angles[small_angles]) / 48
    )
    return quaternions[..., 1:] / sin_half_angles_over_angles


# ============================================================================
# Core conversion functions
# ============================================================================

def accumulate_rotations(relative_rotations):
    """
    Accumulate relative rotation matrices into absolute rotations.
    Args:
        relative_rotations: (T, 3, 3) array of relative rotation matrices
    Returns:
        (T, 3, 3) array of absolute rotation matrices
    """
    R_total = [relative_rotations[0]]
    for R_rel in relative_rotations[1:]:
        R_total.append(np.matmul(R_rel, R_total[-1]))
    return np.array(R_total)


def recover_from_272rpr(motion_data, njoint=22):
    """
    Convert 272-rpr representation back to SMPL-85 format.
    
    SMPL-85 layout:
      [0:3]   global_orient (axis-angle, 3)
      [3:66]  body_pose for 21 SMPL-X body joints (axis-angle, 63)
      [66:72] 2 additional joints (zeros, 6) 
      [72:75] translation (3)
      [75:85] betas (zeros, 10)
    
    Args:
        motion_data: (T, 272) numpy array
        njoint: number of joints (default 22)
    Returns:
        smpl_85: (T, 85) numpy array in SMPL-85 format
    """
    nfrm = motion_data.shape[0]
    
    # Extract components from 272-rpr
    velocities_root_xy = motion_data[:, :2]                          # (T, 2)
    global_heading_diff_6d = motion_data[:, 2:8]                     # (T, 6)
    positions_no_heading = motion_data[:, 8:8+3*njoint].reshape(nfrm, -1, 3)  # (T, 22, 3)
    rotations_6d = motion_data[:, 8+6*njoint:8+12*njoint]           # (T, 132) = (T, 22*6)
    
    # Convert 6D rotations to rotation matrices: (T, 22, 3, 3)
    rotations_matrix = rotation_6d_to_matrix(
        torch.from_numpy(rotations_6d).float().reshape(nfrm, -1, 6)
    ).numpy()
    
    # Recover global heading rotation: accumulate differential heading
    global_heading_rot = accumulate_rotations(
        rotation_6d_to_matrix(torch.from_numpy(global_heading_diff_6d).float()).numpy()
    )  # (T, 3, 3)
    inv_global_heading_rot = np.transpose(global_heading_rot, (0, 2, 1))  # (T, 3, 3)
    
    # Apply inverse heading to root joint rotation to get absolute root rotation
    rotations_matrix[:, 0, ...] = np.matmul(inv_global_heading_rot, rotations_matrix[:, 0, ...])
    
    # Recover root translation from velocity + heading
    velocities_root_xyz = np.zeros((nfrm, 3))
    velocities_root_xyz[:, 0] = velocities_root_xy[:, 0]
    velocities_root_xyz[:, 2] = velocities_root_xy[:, 1]
    # Apply heading rotation to velocity (except first frame)
    velocities_root_xyz[1:, :] = np.matmul(
        inv_global_heading_rot[:-1],
        velocities_root_xyz[1:, :, None]
    ).squeeze(-1)
    
    # Cumulative sum to get position
    root_translation = np.cumsum(velocities_root_xyz, axis=0)
    
    # Set Y (height) from joint positions (hip/root height)
    height = positions_no_heading[:, 0, 1]
    root_translation[:, 1] = height
    
    # Convert rotation matrices to axis-angle
    axis_angle = matrix_to_axis_angle(
        torch.from_numpy(rotations_matrix).float()
    ).numpy().reshape(nfrm, -1)  # (T, 66) = (T, 22*3)
    
    # Construct SMPL-85
    smpl_85 = np.concatenate([
        axis_angle,                           # (T, 66) - 22 joints axis-angle
        np.zeros((nfrm, 6)),                  # (T, 6)  - 2 extra joints (zeros)
        root_translation,                     # (T, 3)  - translation
        np.zeros((nfrm, 10))                  # (T, 10) - betas (zeros)
    ], axis=-1)
    
    return smpl_85


def smpl85_to_amass_npz(smpl_85, output_path, fps=30.0, z_up=False):
    """
    Convert SMPL-85 representation to standard AMASS SMPL .npz format.
    
    SMPL-85 layout:
      [0:3]   global_orient (3)
      [3:72]  body_pose (69 = 23 joints × 3)
      [72:75] translation (3)
      [75:85] betas (10)
    
    AMASS SMPL .npz:
      poses:           (T, 72)  [global_orient(3) + body_pose(69)]
      trans:           (T, 3)
      betas:           (10,)
      gender:          "neutral"
      mocap_framerate: fps
    
    Args:
        smpl_85: (T, 85) numpy array
        output_path: path to save .npz file
        fps: frame rate (default 30.0)
        z_up: if True, convert coordinate system from Y-up to Z-up (default False)
    """
    poses = smpl_85[:, :72]         # (T, 72): global_orient(3) + body_pose(69)
    trans = smpl_85[:, 72:75]       # (T, 3)
    betas = smpl_85[0, 75:85]      # (10,) - take first frame (should be constant)

    if z_up:
        poses, trans = yup_to_zup(poses, trans)

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    
    np.savez(
        output_path,
        poses=poses.astype(np.float32),
        trans=trans.astype(np.float32),
        betas=betas.astype(np.float32),
        gender='neutral',
        mocap_framerate=fps,
    )


def convert_272rpr_to_amass(input_path, output_path, fps=30.0, z_up=False):
    """
    Convert a single 272-rpr .npy file to AMASS SMPL .npz format.
    
    Args:
        input_path: path to input .npy file (T, 272)
        output_path: path to output .npz file
        fps: frame rate (default 30.0)
        z_up: if True, output in Z-up coordinate system (default False)
    """
    # Load 272-rpr data
    motion_data = np.load(input_path)
    
    if motion_data.shape[-1] != 272:
        raise ValueError(f"Expected 272-dim data, got {motion_data.shape[-1]}-dim from {input_path}")
    
    # Convert to SMPL-85
    smpl_85 = recover_from_272rpr(motion_data, njoint=22)
    
    # Save as AMASS npz
    smpl85_to_amass_npz(smpl_85, output_path, fps=fps, z_up=z_up)
    
    return smpl_85


def collect_npy_files(input_dir):
    """
    Recursively collect all .npy files under a directory.
    
    Args:
        input_dir: root directory to search
    Returns:
        List of absolute paths to .npy files, sorted
    """
    npy_files = []
    for root, dirs, files in os.walk(input_dir):
        for f in sorted(files):
            if f.endswith('.npy'):
                npy_files.append(os.path.join(root, f))
    npy_files.sort()
    return npy_files


def _convert_single_task(task):
    """
    Worker function for parallel conversion.
    
    Args:
        task: (input_path, output_path, fps, z_up) tuple
    Returns:
        (input_path, output_path, success, n_frames, error_msg) tuple
    """
    input_path, output_path, fps, z_up = task
    try:
        smpl_85 = convert_272rpr_to_amass(input_path, output_path, fps=fps, z_up=z_up)
        return (input_path, output_path, True, smpl_85.shape[0], "")
    except Exception as e:
        return (input_path, output_path, False, 0, str(e))


def convert_directory(input_dir, output_dir, fps=30.0, skip_existing=False, workers=1, z_up=False):
    """
    Recursively convert all .npy files in a directory tree,
    preserving the folder structure in the output directory.
    
    Args:
        input_dir: root directory containing .npy files
        output_dir: root directory to save .npz files (mirrors input structure)
        fps: frame rate (default 30.0)
        skip_existing: skip files that already have a corresponding .npz output
        workers: number of parallel workers (1 = sequential)
        z_up: if True, output in Z-up coordinate system (default False)
    Returns:
        dict with conversion statistics
    """
    input_dir = os.path.abspath(input_dir)
    output_dir = os.path.abspath(output_dir)

    # ------------------------------------------------------------------ scan
    print(f"Scanning: {input_dir}")
    npy_files = collect_npy_files(input_dir)
    total_found = len(npy_files)
    print(f"Found {total_found} .npy files")

    if total_found == 0:
        print("No .npy files found. Nothing to do.")
        return {"found": 0, "converted": 0, "skipped": 0, "failed": 0}

    # ----------------------------------------------------------- build tasks
    tasks = []
    skipped = 0
    for npy_path in npy_files:
        rel_path = os.path.relpath(npy_path, input_dir)
        out_path = os.path.join(output_dir, os.path.splitext(rel_path)[0] + '.npz')

        if skip_existing and os.path.exists(out_path):
            skipped += 1
            continue

        tasks.append((npy_path, out_path, fps, z_up))

    if skipped > 0:
        print(f"Skipping {skipped} already converted files (--skip_existing)")

    if len(tasks) == 0:
        print("All files already converted. Nothing to do.")
        return {"found": total_found, "converted": 0, "skipped": skipped, "failed": 0}

    print(f"Converting {len(tasks)} files...")
    print(f"  Input root:  {input_dir}")
    print(f"  Output root: {output_dir}")
    if workers > 1:
        print(f"  Workers:     {workers}")
    print()

    # ------------------------------------------------------------ conversion
    success_count = 0
    fail_count    = 0
    total_frames  = 0
    failed_files  = []

    t_start = time.time()

    if workers > 1:
        # ---- parallel ----
        with Pool(processes=workers) as pool:
            for inp, outp, success, n_frames, err_msg in tqdm(
                pool.imap(_convert_single_task, tasks),
                total=len(tasks),
                desc="Converting",
                unit="file",
            ):
                rel = os.path.relpath(inp, input_dir)
                if success:
                    success_count += 1
                    total_frames  += n_frames
                    logger.info("[OK]     %s  (%d frames)", rel, n_frames)
                else:
                    fail_count += 1
                    failed_files.append((inp, err_msg))
                    logger.warning("[FAILED] %s  |  %s", rel, err_msg)
    else:
        # ---- sequential ----
        for input_path, output_path, task_fps, task_zup in tqdm(
            tasks, desc="Converting", unit="file"
        ):
            rel = os.path.relpath(input_path, input_dir)
            try:
                smpl_85 = convert_272rpr_to_amass(input_path, output_path,
                                                  fps=task_fps, z_up=task_zup)
                success_count += 1
                total_frames  += smpl_85.shape[0]
                logger.info("[OK]     %s  (%d frames)", rel, smpl_85.shape[0])
            except Exception as e:
                fail_count += 1
                failed_files.append((input_path, str(e)))
                logger.warning("[FAILED] %s  |  %s", rel, e)

    elapsed = time.time() - t_start

    # ---------------------------------------------------------------- summary
    print(f"\n{'='*60}")
    print(f"Batch Conversion Summary")
    print(f"{'='*60}")
    print(f"  Total found:    {total_found} files")
    print(f"  Converted:      {success_count} files")
    print(f"  Skipped:        {skipped} files")
    print(f"  Failed:         {fail_count} files")
    print(f"  Total frames:   {total_frames} ({total_frames / fps:.1f}s @ {fps}fps)")
    print(f"  Time elapsed:   {elapsed:.1f}s")
    if success_count > 0 and elapsed > 0:
        print(f"  Speed:          {success_count / elapsed:.1f} files/s, {total_frames / elapsed:.0f} frames/s")
    print(f"  Output dir:     {output_dir}")
    print(f"{'='*60}")

    if failed_files:
        print(f"\nFailed files ({len(failed_files)}):")
        for fpath, err in failed_files[:20]:
            rel = os.path.relpath(fpath, input_dir)
            print(f"  {rel}: {err}")
        if len(failed_files) > 20:
            print(f"  ... and {len(failed_files) - 20} more")
    
    return {
        "found": total_found,
        "converted": success_count,
        "skipped": skipped,
        "failed": fail_count,
        "total_frames": total_frames,
        "elapsed": elapsed,
        "failed_files": failed_files,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Convert MotionMillion 272-rpr .npy to AMASS SMPL .npz format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single file:
  python convert_272rpr_to_amass_smpl.py \\
      --input motion_272rpr/.../band_pull_apart_slice_1.npy \\
      --output output/band_pull_apart_slice_1.npz

  # Batch convert a directory (recursive, preserves folder structure):
  python convert_272rpr_to_amass_smpl.py \\
      --input motion_272rpr/MotionLLAMA/fit3d \\
      --output output/fit3d_amass

  # Batch convert, skip existing, use 4 parallel workers:
  python convert_272rpr_to_amass_smpl.py \\
      --input motion_272rpr/ \\
      --output output_amass/ \\
      --skip_existing --workers 4
"""
    )
    parser.add_argument('--input', type=str, required=True,
                        help='Path to a .npy file or a directory of .npy files')
    parser.add_argument('--output', type=str, required=True,
                        help='Output .npz file path (single file) or output directory (batch)')
    parser.add_argument('--fps', type=float, default=30.0,
                        help='Motion frame rate (default: 30.0)')
    parser.add_argument('--skip_existing', action='store_true',
                        help='Skip conversion if output .npz already exists')
    parser.add_argument('--workers', type=int, default=1,
                        help='Number of parallel workers for batch conversion (default: 1)')
    parser.add_argument('--z_up', action='store_true',
                        help='Convert coordinate system from Y-up to Z-up (x\'=x, y\'=-z, z\'=y)')
    parser.add_argument('--log_level', type=str, default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='Logging verbosity level (default: INFO)')
    parser.add_argument('--log_file', type=str, default=None,
                        help='Optional path to write log output to a file (in addition to stdout)')

    args = parser.parse_args()

    # ---- configure logging as early as possible ----
    setup_logging(log_level=args.log_level, log_file=args.log_file)
    
    input_path = os.path.abspath(args.input)
    output_path = os.path.abspath(args.output)
    
    if os.path.isfile(input_path):
        # ===================== Single file conversion =====================
        if not input_path.endswith('.npy'):
            print(f"Error: Input file must be a .npy file, got: {input_path}")
            sys.exit(1)
        
        # If output is a directory, auto-generate output filename
        if os.path.isdir(output_path) or output_path.endswith('/'):
            basename = os.path.splitext(os.path.basename(input_path))[0] + '.npz'
            output_path = os.path.join(output_path, basename)
        elif not output_path.endswith('.npz'):
            output_path = output_path + '.npz'
        
        print(f"Converting single file:")
        print(f"  Input:  {input_path}")
        print(f"  Output: {output_path}")
        print()

        smpl_85 = convert_272rpr_to_amass(input_path, output_path, fps=args.fps, z_up=args.z_up)

        data = np.load(output_path)
        logger.info("[OK]     %s  (%d frames)", os.path.basename(input_path), smpl_85.shape[0])
        print(f"Conversion complete!")
        print(f"  Input shape:  ({smpl_85.shape[0]}, 272)")
        print(f"  Output keys:  {list(data.keys())}")
        print(f"  poses:        {data['poses'].shape} (global_orient + body_pose)")
        print(f"  trans:        {data['trans'].shape}")
        print(f"  betas:        {data['betas'].shape}")
        print(f"  gender:       {str(data['gender'])}")
        print(f"  framerate:    {float(data['mocap_framerate'])} fps")
        print(f"  Duration:     {smpl_85.shape[0] / args.fps:.2f} seconds")
        
    elif os.path.isdir(input_path):
        # ===================== Batch directory conversion =====================
        stats = convert_directory(
            input_dir=input_path,
            output_dir=output_path,
            fps=args.fps,
            skip_existing=args.skip_existing,
            workers=args.workers,
            z_up=args.z_up,
        )
        
        if stats['failed'] > 0:
            sys.exit(1)
    else:
        print(f"Error: Input path does not exist: {input_path}")
        sys.exit(1)


if __name__ == '__main__':
    main()

