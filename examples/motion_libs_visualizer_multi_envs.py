# SPDX-FileCopyrightText: Copyright (c) 2025 The ProtoMotions Developers
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Multi-environment MotionLib visualizer.

This script visualizes one MotionLib `.pt` file across many parallel environments.
Use `--num_envs` to control how many environments are created.
"""

import argparse
import math
import os
from pathlib import Path
from typing import Dict, Optional


parser = argparse.ArgumentParser(description="Visualize motions in many parallel envs")
parser.add_argument(
    "--motion_file",
    type=str,
    required=True,
    help="Path to a MotionLib .pt file",
)
parser.add_argument(
    "--num_envs",
    type=int,
    default=8,
    help="Number of parallel environments to visualize",
)
parser.add_argument(
    "--simulator",
    type=str,
    choices=["isaacgym", "isaaclab", "newton"],
    default="isaacgym",
    help="Simulator backend",
)
parser.add_argument(
    "--robot",
    type=str,
    choices=["g1", "rigv1", "h1_2", "smpl"],
    default="g1",
    help="Robot model",
)
parser.add_argument("--headless", action="store_true", help="Run without GUI")
parser.add_argument(
    "--cpu-only",
    action="store_true",
    default=False,
    help="Use CPU only",
)
parser.add_argument(
    "--playback_speed",
    type=float,
    default=1.0,
    help="Playback speed multiplier (1.0 = normal)",
)
parser.add_argument(
    "--start_motion_idx",
    type=int,
    default=0,
    help="First motion index to assign to env 0",
)
parser.add_argument(
    "--sequential_env_motions",
    action="store_true",
    help="Use sequential motion IDs across envs instead of random assignment",
)
parser.add_argument(
    "--random_start_frame",
    action="store_true",
    default=True,
    help="Randomize start frame when an env gets/reset a motion",
)
parser.add_argument(
    "--loop_mode",
    type=str,
    choices=["same_batch", "next_batch"],
    default="same_batch",
    help=(
        "How to handle reset key R: "
        "'same_batch' keeps the same motion IDs, 'next_batch' shifts all envs to the next motion batch"
    ),
)
parser.add_argument(
    "--camera_mode",
    type=str,
    choices=["follow", "fixed"],
    default="fixed",
    help="Viewer camera mode: follow robot target or fixed world camera",
)
parser.add_argument(
    "--camera_pos",
    type=float,
    nargs=3,
    default=None,
    help="Optional fixed camera position (x y z). Works with IsaacGym/IsaacLab",
)
parser.add_argument(
    "--camera_target",
    type=float,
    nargs=3,
    default=None,
    help="Optional fixed camera target/look-at (x y z). Works with IsaacGym/IsaacLab",
)
parser.add_argument(
    "--env_offset_xy",
    type=float,
    default=3.0,
    help="XY spacing (meters) between parallel environments",
)
args = parser.parse_args()

# Import simulator before torch - required for IsaacGym/IsaacLab.
from protomotions.utils.simulator_imports import import_simulator_before_torch  # noqa: E402

AppLauncher = import_simulator_before_torch(args.simulator)

import torch  # noqa: E402

from protomotions.utils.hydra_replacement import get_class  # noqa: E402
from protomotions.simulator.factory import simulator_config  # noqa: E402
from protomotions.robot_configs.factory import robot_config  # noqa: E402
from protomotions.robot_configs.base import ControlType  # noqa: E402
from protomotions.components.motion_lib import MotionLib, MotionLibConfig  # noqa: E402
from protomotions.simulator.base_simulator.config import (  # noqa: E402
    VisualizationMarkerConfig,
    MarkerConfig,
    MarkerState,
)
from protomotions.components.scene_lib import (  # noqa: E402
    SceneLib,
    MeshSceneObject,
    Scene,
    ObjectOptions,
    SceneLibConfig,
    ReplicationMethod,
    SubsetMethod,
)


def create_checkerboard_ground(
    num_envs: int, device: torch.device, simulator_type: str = "isaacgym"
) -> SceneLib:
    """Create a checkerboard ground mesh scene replicated for each env."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    checkerboard_dir = os.path.join(
        project_root, "protomotions/data/assets/checkerboard"
    )

    if simulator_type == "isaaclab":
        asset_path = os.path.join(checkerboard_dir, "checkerboard_ground.usda")
    else:
        asset_path = os.path.join(checkerboard_dir, "checkerboard_ground.urdf")

    if not os.path.exists(asset_path):
        print(f"Warning: checkerboard asset not found at {asset_path}")
        print("Falling back to empty scene")
        return SceneLib.empty(num_envs=num_envs, device=device)

    texture_path = None
    if simulator_type != "isaaclab":
        texture_file = os.path.join(checkerboard_dir, "checkerboard_texture.png")
        if os.path.exists(texture_file):
            texture_path = texture_file

    scenes = []
    for _ in range(num_envs):
        ground_mesh = MeshSceneObject(
            object_path=asset_path,
            translation=(0.0, 0.0, -0.005),
            rotation=(0.0, 0.0, 0.0, 1.0),
            options=ObjectOptions(
                fix_base_link=True,
                vhacd_enabled=False,
                texture_path=texture_path,
            ),
        )
        scenes.append(Scene(objects=[ground_mesh], offset=(0.0, 0.0)))

    scene_lib_config = SceneLibConfig(
        scene_file=None,
        replicate_method=ReplicationMethod.SEQUENTIAL,
        subset_method=SubsetMethod.FIRST,
        pointcloud_samples_per_object=None,
    )

    return SceneLib(
        config=scene_lib_config,
        num_envs=num_envs,
        scenes=scenes,
        device=device,
        terrain=None,
    )


class MultiEnvMotionLibVisualizer:
    def __init__(
        self,
        motion_file: Path,
        num_envs: int,
        robot_name: str,
        simulator_type: str,
        headless: bool,
        cpu_only: bool,
        playback_speed: float,
        start_motion_idx: int,
        sequential_env_motions: bool,
        random_start_frame: bool,
        loop_mode: str,
        camera_mode: str,
        camera_pos,
        camera_target,
        env_offset_xy: float,
        extra_simulator_params: Optional[dict] = None,
    ):
        if num_envs <= 0:
            raise ValueError("--num_envs must be > 0")
        if playback_speed <= 0:
            raise ValueError("--playback_speed must be > 0")

        self.motion_file = motion_file
        self.num_envs = num_envs
        self.robot_name = robot_name
        self.simulator_type = simulator_type
        self.headless = headless
        self.playback_speed = playback_speed
        self.loop_mode = loop_mode
        self.sequential_env_motions = sequential_env_motions
        self.random_start_frame = random_start_frame
        self.camera_mode = camera_mode
        self.camera_pos = camera_pos
        self.camera_target = camera_target
        self.env_offset_xy = env_offset_xy
        self.device = torch.device("cuda:0" if not cpu_only else "cpu")

        self.motion_lib = MotionLib(
            config=MotionLibConfig(motion_file=str(self.motion_file)),
            device=self.device,
        )
        self.total_motions = self.motion_lib.num_motions()
        if self.total_motions <= 0:
            raise RuntimeError(f"No motions found in {self.motion_file}")

        self.base_motion_idx = start_motion_idx % self.total_motions
        self.motion_ids = self._build_motion_ids(self.base_motion_idx)
        self.motion_num_frames = self.motion_lib.get_motion_num_frames(None)
        self.current_frames = torch.zeros(self.num_envs, dtype=torch.long, device=self.device)
        self.current_lengths = self.motion_num_frames[self.motion_ids].clone()
        self._sample_start_frames(torch.ones(self.num_envs, dtype=torch.bool, device=self.device))
        self.env_root_offsets = self._build_env_offsets()

        self.robot_cfg = robot_config(self.robot_name)
        self.kinematic_info = self.robot_cfg.kinematic_info

        self.simulator_cfg = simulator_config(
            self.simulator_type,
            self.robot_cfg,
            headless=self.headless,
            num_envs=self.num_envs,
            experiment_name="motion_lib_multi_env_viz",
        )

        # Visualization-only settings.
        self.robot_cfg.asset.disable_gravity = True
        self.robot_cfg.asset.fix_base_link = False
        self.robot_cfg.asset.self_collisions = False
        self.robot_cfg.control.control_type = ControlType.TORQUE

        # Contact marker state (purple spheres for bodies in contact).
        self.contact_marker_name = "contact_markers"
        self.viz_markers = self._create_visualization_markers()
        self._latest_contact_mask = torch.zeros(
            self.num_envs,
            self.kinematic_info.num_bodies,
            dtype=torch.bool,
            device=self.device,
        )

        custom_key_handlers = {"R": self.next_motion_batch}
        SimulatorClass = get_class(self.simulator_cfg._target_)
        extra_params = extra_simulator_params or {}
        scene_lib = create_checkerboard_ground(
            num_envs=self.simulator_cfg.num_envs,
            device=self.device,
            simulator_type=self.simulator_type,
        )
        self.simulator = SimulatorClass(
            config=self.simulator_cfg,
            robot_config=self.robot_cfg,
            terrain=None,
            device=self.device,
            scene_lib=scene_lib,
            custom_key_handlers=custom_key_handlers,
            **extra_params,
        )
        self.simulator._initialize_with_markers(self.viz_markers)
        self._configure_camera()

        self.step_count = 0
        print("==== Multi-env Motion Visualizer ====")
        print(f"Motion file: {self.motion_file}")
        print(f"Total motions in file: {self.total_motions}")
        print(f"Num envs: {self.num_envs}")
        print(f"Playback speed: {self.playback_speed:.3f}x")
        print(f"Camera mode: {self.camera_mode}")
        print(f"Env XY spacing: {self.env_offset_xy:.2f}m")
        print("Press 'R' to switch to next motion batch")

    def _create_visualization_markers(self) -> Dict[str, VisualizationMarkerConfig]:
        contact_marker_configs = [
            MarkerConfig(size="regular") for _ in range(self.kinematic_info.num_bodies)
        ]
        return {
            self.contact_marker_name: VisualizationMarkerConfig(
                type="sphere",
                color=(0.8, 0.0, 0.8),  # Purple for contact
                markers=contact_marker_configs,
            )
        }

    def _update_contact_markers(self) -> Dict[str, MarkerState]:
        all_body_state = self.simulator.get_bodies_state()
        all_translations = all_body_state.rigid_body_pos.detach().clone()
        all_orientations = all_body_state.rigid_body_rot.detach().clone()

        # Only show markers for bodies in contact. Hide others below ground.
        mask = self._latest_contact_mask.unsqueeze(-1)
        hidden_pos = torch.tensor([0.0, 0.0, -100.0], device=self.device).view(1, 1, 3)
        contact_translations = torch.where(mask, all_translations, hidden_pos)
        return {
            self.contact_marker_name: MarkerState(
                translation=contact_translations,
                orientation=all_orientations,
            )
        }

    def _build_motion_ids(self, start_idx: int) -> torch.Tensor:
        if self.sequential_env_motions:
            ids = (torch.arange(self.num_envs, device=self.device) + start_idx) % self.total_motions
        else:
            ids = torch.randint(
                low=0,
                high=self.total_motions,
                size=(self.num_envs,),
                device=self.device,
            )
        return ids.to(torch.long)

    def _refresh_lengths(self):
        self.current_lengths = self.motion_num_frames[self.motion_ids].clone()

    def _build_env_offsets(self) -> torch.Tensor:
        """Build a square grid of XY offsets so each env is spatially separated."""
        grid_w = math.ceil(math.sqrt(self.num_envs))
        idx = torch.arange(self.num_envs, device=self.device)
        x = (idx % grid_w).float() * self.env_offset_xy
        y = (idx // grid_w).float() * self.env_offset_xy
        return torch.stack([x, y, torch.zeros_like(x)], dim=-1)

    def _sample_start_frames(self, mask: torch.Tensor):
        if not mask.any():
            return
        if not self.random_start_frame:
            self.current_frames[mask] = 0
            return
        lengths = self.current_lengths[mask]
        rand_unit = torch.rand(lengths.shape[0], device=self.device)
        random_frames = (rand_unit * lengths.float()).long()
        random_frames = torch.minimum(random_frames, torch.clamp(lengths - 1, min=0))
        self.current_frames[mask] = random_frames

    def _configure_camera(self):
        if self.headless:
            return

        if self.simulator_type == "isaacgym":
            if self.camera_pos is not None and self.camera_target is not None:
                from isaacgym import gymapi

                cam_pos = gymapi.Vec3(*self.camera_pos)
                cam_target = gymapi.Vec3(*self.camera_target)
                self.simulator._gym.viewer_camera_look_at(
                    self.simulator._viewer, None, cam_pos, cam_target
                )

            if self.camera_mode == "fixed":
                self.simulator._update_camera = lambda: None
        elif self.simulator_type == "isaaclab":
            if self.camera_pos is not None and self.camera_target is not None:
                self.simulator._sim.set_camera_view(self.camera_pos, self.camera_target)
            if self.camera_mode == "fixed":
                self.simulator._update_camera = lambda: None
        else:
            # Newton handles camera updates internally; keep follow behavior.
            if self.camera_mode == "fixed":
                print("Warning: fixed camera mode is not implemented for newton backend")

    def next_motion_batch(self):
        if self.loop_mode == "next_batch":
            self.base_motion_idx = (
                self.base_motion_idx + (self.num_envs if self.sequential_env_motions else 1)
            ) % self.total_motions
            self.motion_ids = self._build_motion_ids(self.base_motion_idx)
            self._refresh_lengths()

        self._sample_start_frames(
            torch.ones(self.num_envs, dtype=torch.bool, device=self.device)
        )
        print(
            f"Reset to batch start idx={self.base_motion_idx}, "
            f"env[0] motion={self.motion_ids[0].item()}"
        )
        return True

    def _set_robot_pose(self, dof_pos, rigid_body_pos, rigid_body_rot):
        current_state = self.simulator.get_robot_state()
        current_state.dof_pos = dof_pos.detach()
        current_state.dof_vel = torch.zeros_like(current_state.dof_pos).detach()

        root_pos = rigid_body_pos.detach()[:, 0, :].clone()
        root_pos[:, :2] += self.env_root_offsets[:, :2]
        current_state.rigid_body_pos[:, 0, :] = root_pos
        current_state.rigid_body_rot[:, 0, :] = rigid_body_rot.detach()[:, 0, :]
        current_state.rigid_body_vel[:, 0, :] = torch.zeros(
            self.num_envs, 3, device=self.device
        )
        current_state.rigid_body_ang_vel[:, 0, :] = torch.zeros(
            self.num_envs, 3, device=self.device
        )

        env_ids = torch.arange(self.num_envs, device=self.device)
        self.simulator.reset_envs(current_state, env_ids=env_ids)

    def _advance_frames(self):
        if self.playback_speed < 1.0:
            frames_per_step = max(1, int(1.0 / self.playback_speed))
            inc = 1 if (self.step_count % frames_per_step == 0) else 0
        else:
            inc = max(1, int(self.playback_speed))

        if inc > 0:
            self.current_frames += inc
            loop_mask = self.current_frames >= self.current_lengths
            if loop_mask.any():
                num_done = int(loop_mask.sum().item())
                if self.sequential_env_motions:
                    self.motion_ids[loop_mask] = (
                        self.motion_ids[loop_mask] + self.num_envs
                    ) % self.total_motions
                else:
                    self.motion_ids[loop_mask] = torch.randint(
                        low=0,
                        high=self.total_motions,
                        size=(num_done,),
                        device=self.device,
                    )
                self.current_lengths[loop_mask] = self.motion_num_frames[
                    self.motion_ids[loop_mask]
                ]
                self._sample_start_frames(loop_mask)

    def run(self):
        while True:
            if self.simulator.user_requested_reset:
                self.next_motion_batch()
                self.simulator.user_requested_reset = False

            state = self.motion_lib.get_motion_state_exact_frame(
                self.motion_ids,
                self.current_frames,
            )
            self._set_robot_pose(
                dof_pos=state.dof_pos,
                rigid_body_pos=state.rigid_body_pos,
                rigid_body_rot=state.rigid_body_rot,
            )
            if state.rigid_body_contacts is not None:
                self._latest_contact_mask = state.rigid_body_contacts.to(torch.bool)
            else:
                self._latest_contact_mask.zero_()

            zero_actions = torch.zeros(
                self.num_envs,
                self.kinematic_info.num_dofs,
                device=self.device,
            )
            self.simulator.step(
                zero_actions, markers_callback=lambda: self._update_contact_markers()
            )

            self._advance_frames()
            self.step_count += 1


def main():
    device = torch.device("cuda:0") if not args.cpu_only else torch.device("cpu")

    extra_simulator_params = {}
    if args.simulator == "isaaclab":
        app_launcher_flags = {
            "headless": args.headless,
            "device": str(device),
        }
        app_launcher = AppLauncher(app_launcher_flags)
        extra_simulator_params["simulation_app"] = app_launcher.app

    visualizer = MultiEnvMotionLibVisualizer(
        motion_file=Path(args.motion_file),
        num_envs=args.num_envs,
        robot_name=args.robot,
        simulator_type=args.simulator,
        headless=args.headless,
        cpu_only=args.cpu_only,
        playback_speed=args.playback_speed,
        start_motion_idx=args.start_motion_idx,
        sequential_env_motions=args.sequential_env_motions,
        random_start_frame=args.random_start_frame,
        loop_mode=args.loop_mode,
        camera_mode=args.camera_mode,
        camera_pos=args.camera_pos,
        camera_target=args.camera_target,
        env_offset_xy=args.env_offset_xy,
        extra_simulator_params=extra_simulator_params,
    )

    try:
        visualizer.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        visualizer.simulator.close()


if __name__ == "__main__":
    main()
