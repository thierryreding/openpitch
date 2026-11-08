# Models and references to evaluate

Starting detector: Ultralytics YOLO
([0007](../decisions/0007-ultralytics-as-baseline-detector.md)). Everything else here is
still under evaluation. Check the license of every model, weight file and dataset before
adopting it. Never commit weights to the repo.

- **Ultralytics YOLO (+ ByteTrack, supervision)**: the common baseline in community
  football projects: detect and track players, referees and the ball, KMeans on shirt
  colors for teams, optical flow for camera motion, a perspective transform. AGPL-3.0
  code and weights, kept behind the detector backend as part of the `gpu` extra.
- **Permissively licensed detectors** (RT-DETR family, RF-DETR, D-FINE style): the
  alternatives if the AGPL dependency becomes a problem.
- **SoccerNet** (soccer-net.org, github.com/SoccerNet): a dataset and benchmark platform
  for broadcast soccer video: action spotting, ball action spotting, tracking (with
  jersey numbers and teams), camera calibration, re-identification. Of interest: the
  released calibration network (distilled from a commercial tool, trained on 500
  broadcast games) as an auto-calibration candidate, and action spotting to auto-suggest
  clips (long term). Caveat: broadcast footage looks very different from sideline or
  fixed cameras, so transfer must be tested.
- **NVIDIA TAO models on NGC** (PeopleNet, PeopleNet-Transformer, pose, action
  recognition, re-identification): optimized for TensorRT/DeepStream and Jetson (Orin NX
  supported), so candidates for the live phase. Caveats:
  - The model cards say they can only be used with TAO/DeepStream/TensorRT.
  - PeopleNet-Transformer is not trained on fish-eye or moving cameras.
  - They detect people only (no ball, no team/referee), so fine-tuning would need labeled
    football data.
  - The NVIDIA Open Model License has an acceptable-use addendum and may be updated. GPL
    compatibility is unclear.
- **Deep point trackers** (CoTracker, TAPIR): an alternative for PTZ homography
  propagation, but heavier.

Benchmark every candidate on real footage (4K Falcon, wide-angle Osmo, small-sided and 11v11 games)
for small-player recall, tracking identity switches and speed.
