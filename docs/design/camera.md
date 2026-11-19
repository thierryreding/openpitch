# Camera calibration

Camera calibration finds a camera's lens geometry: focal length, principal point,
distortion and field of view. It is a setup step, done once per camera and recording
mode. Not to be confused with *pitch* calibration, which maps image points to the pitch
(homography, see [pipeline.md](pipeline.md)); pitch calibration builds on it.

`openpitch.core.camera` implements it with OpenCV (the `cv` extra, imported lazily).

## Workflow
1. `openpitch camera board` makes a ChArUco board that fills a screen: a checkerboard with
   an ArUco marker in each white square, so every corner can be identified even when only
   part of the board is visible. That gives corners up to the image edges, where
   distortion is largest. The image is written as a PNG with its description (the
   `BoardSpec`) next to it as JSON, so calibration always detects exactly the board that
   was shown. `--size` is the screen's native resolution; `--screen-mm`, its physical
   size, is informational: focal length, distortion and field of view do not depend on
   it. The CLI does not detect screens: that needs a GUI toolkit, and the CLI never
   depends on one.
2. Show the PNG full-screen (a web browser with F11 works) and record 20-30 s in exactly
   the mode to calibrate. Keep the camera still and move the screen through the whole
   image, corners and edges included, tilted up to about 45 degrees, at about 0.7-1.2 m.
3. `openpitch camera calibrate VIDEO` detects the board in every 4th frame (decoding on the
   GPU when it can), picks up to 60 frames that cover the image, and fits a pinhole model
   three ways: no distortion, radial `k1 k2`, and OpenCV's `k1 k2 p1 p2 k3`. It keeps the
   simplest model whose RMS is within 10% of the best: extra terms fitted on noise only
   make the edges worse. It writes a camera profile.

Planned: the same workflow in Studio, which finds its screen's resolution and physical
size through Qt (portable), generates the board for it, shows it full-screen and
calibrates while the user moves the laptop in front of the camera.

## Camera profile
A JSON file (`CameraProfile`, `kind: "camera_profile"`, `version: 1`):
- `camera`: model, serial number and firmware, from the recording's metadata where it has
  any (DJI `CAM meta`).
- `mode`: resolution, frame rate, and the camera's FOV and stabilization settings where
  the metadata records them. A profile is valid for one mode only: another FOV setting,
  stabilization (which crops) or resolution needs its own profile.
- `intrinsics` (`fx`, `fy`, `cx`, `cy` in source pixels), `distortion_model` and
  `distortion` (always OpenCV order `k1 k2 p1 p2 k3`, zeros for unused terms), `rms_px`
  and `fov` (horizontal, vertical and diagonal degrees after undistortion).
- `fits`: every model that was fitted, for comparison; `frames_used`, `corners_used` and
  `coverage` (8x6 image cells with detected corners).
- `board`, `source` (fingerprint and file name of the calibration video), `created_at`,
  `tool`.

Still open: where profiles live and how a recording finds its profile (by camera model,
serial and mode from the metadata). That makes the format a lasting promise, so it gets
a decision record once something reads profiles.

## Results
DJI Osmo Action 6, 4:3 4K at 59.94 fps, Standard (Dewarp) FOV, ChArUco board on a laptop
screen (2560x1600, 21.6 mm squares):

| | model | RMS | focal length | horizontal FOV | vertical | diagonal |
|---|---|---|---|---|---|---|
| stabilization off | none | 0.28-0.30 px | 1512-1517 px | 103.5° | 87.2° | 115.6° |
| stabilization on | none | 0.38-0.46 px | 1734-1800 px | 93.7-95.8° | 77-79° | 106-108° |

- Standard (Dewarp) is rectilinear: the camera removes the lens distortion, and
  distortion terms improve the fit by less than 0.03 px.
- With stabilization off, fits on disjoint halves of the frames agree within 0.3%. With
  stabilization on, they vary by up to 4% in focal length and about 16 px in principal
  point, although the camera stood still: stabilization changes its crop or rotation
  over time. Its geometry is therefore only approximately constant.
- Stabilization crops about 10° of horizontal FOV.

For the two-camera rig (two cameras side by side, angled outwards; see
[overview.md](overview.md)), cameras whose axes are β apart cover β + HFOV with
HFOV − β of overlap. For 180°, β is 76° with stabilization off (28° overlap, about 32% of
the image width at the edge) and 86° with it on (7°, about 11%). Stabilization off gives
an exact geometry and room for stitching; sway from wind could then be removed in
software, from the image or from the per-frame IMU orientation in the DJI metadata.
