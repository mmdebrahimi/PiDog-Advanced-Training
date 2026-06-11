# Vision Research Report: Face/Person Detection on Raspberry Pi 4

> Deep research into the latest and best face detection + tracking options that fit on a Raspberry Pi 4 (ARM64, 4GB RAM, no accelerator).

---

## Executive Summary

**Winner for our use case: YuNet** (already on disk) — best speed/accuracy/simplicity tradeoff. No model change needed. The real gains come from the tracking pipeline (MOSSE, already implemented) and servo smoothing (already tuned).

If we ever want more speed: **Ultra-Light-Fast slim-320 via OpenCV DNN** (~40 FPS) is the upgrade path. For a hardware upgrade: **Pi 5 + Hailo-8L** transforms everything.

---

## Benchmark Data (Raspberry Pi 4, 64-bit, 640x480 unless noted)

### Face Detection Models — Pi 4 Benchmarks

| Model | Framework | FPS on Pi 4 | mAP (WIDER FACE) | Model Size | Python-friendly |
|-------|-----------|-------------|-------------------|------------|-----------------|
| **Ultra-Light slim-320** | MNN | **65** | 67.1% | ~1 MB | No (C++ only) |
| **Ultra-Light RFB-320** | MNN | 56 | 69.8% | ~1 MB | No (C++ only) |
| **Ultra-Light slim-320** | OpenCV DNN | **40** | 67.1% | ~1 MB | Yes |
| **Ultra-Light RFB-320** | OpenCV DNN | 35 | 69.8% | ~1 MB | Yes |
| **Ultra-Light slim-320** | ncnn | 26 | 67.1% | ~1 MB | No |
| **YuNet** | OpenCV DNN | **~25-30** | 81.1% (hard) | 337 KB | Yes (cv2.FaceDetectorYN) |
| **Haar cascade** | OpenCV | ~25-40 | ~60% | 900 KB | Yes |
| **MediaPipe Face** | TFLite | **~10-12** | 74.3% | ~1 MB | Yes |
| **RetinaFace MobileNet** | ONNX | ~8-15 (est.) | 99.4% | ~2 MB | Yes |
| **SCRFD-500MF** | ONNX | ~10-20 (est.) | 80%+ | ~2 MB | Yes |
| **YOLOv8n face** | TFLite | ~2 (470ms) | 93.8% | ~6 MB | Yes |
| **LFFD 5-stage** | ncnn | 4.85 | 88.6% | ~5 MB | No |

Source: [Q-engineering benchmark](https://github.com/Qengineering/Face-detection-Raspberry-Pi-32-64-bits), [LearnOpenCV comparison](https://learnopencv.com/what-is-face-detection-the-ultimate-guide/)

### Person Detection Models

| Model | Framework | FPS on Pi 4 | Notes |
|-------|-----------|-------------|-------|
| **SSD MobileNet V2** (current) | TFLite | ~8-10 | COCO person class, 300x300 input |
| **EfficientDet-Lite0** | TFLite | ~5-8 | Higher accuracy, already on disk |
| **YOLOv8n** | TFLite | ~2 | Too slow without accelerator |

### Tracking Algorithms

| Tracker | FPS on Pi 4 | Accuracy | Best for |
|---------|-------------|----------|----------|
| **MOSSE** (implemented) | 450+ | Low-medium | Inter-frame gap filling |
| **KCF** | 100-200 | Medium | Better accuracy than MOSSE |
| **CSRT** | ~25 | High | Too slow for inter-frame use |
| **SORT** (implemented) | Very fast | Medium | Multi-object, Kalman-based |
| **ByteTrack** | Fast | Better | Better occlusion handling than SORT |

---

## Analysis for Our Use Case

### What we need
- Track ONE person (Alice) from ground level
- Camera: OV5647 CSI 640x480
- Servo update rate: 30 Hz
- Face ID: SFace embeddings (already working)
- Must handle: side faces, partial occlusion, child at ground-level angle

### Current pipeline (after today's changes)
```
TFLite SSD person detect (~10 FPS)
  → YuNet face detect (every frame, ~25 FPS on ROI)
    → MOSSE inter-frame tracker (450+ FPS)
      → Kalman filter (SORT)
        → ServoController (proportional + EMA, 30 Hz)
          → Dead zone (center 10% no-move)
```

### Assessment: Is this already optimal?

**Yes, for Pi 4 without accelerator.** Here's why:

1. **YuNet is the best Python-accessible face detector for Pi 4.** It has 81.1% mAP (hard) vs Ultra-Light's 67.1%, with comparable speed (~25 vs ~40 FPS via OpenCV DNN). The only faster option (Ultra-Light via MNN at 65 FPS) requires C++ and the MNN framework — not worth the complexity for our use case.

2. **MOSSE fills the FPS gap perfectly.** Between 10 FPS detection cycles, MOSSE provides 30 Hz position updates at <2ms per frame. This is exactly the pattern used by successful face-following robot projects.

3. **The bottleneck is now TFLite person detection, not face detection.** SSD MobileNet runs at ~10 FPS and is needed only as a fallback when faces aren't visible. YuNet on the full frame (without person ROI) would run at ~25 FPS — potentially faster than the two-stage pipeline.

### Potential improvements (ranked by impact)

| # | Change | Impact | Effort | Recommended? |
|---|--------|--------|--------|-------------|
| 1 | **Run YuNet on full frame first, TFLite person detect only as fallback** | +5-10 FPS (skip TFLite when face visible) | Medium | Yes — biggest win |
| 2 | **Switch to Ultra-Light slim-320 via OpenCV DNN** | ~40 FPS face detect (from ~25) | Low | Maybe — only if YuNet proves too slow |
| 3 | **Add SCRFD-500MF** | Better small-face detection | Medium | No — overkill for single-person tracking |
| 4 | **RetinaFace MobileNet** | Highest accuracy (99.4%) | Medium | No — too slow (~8-15 FPS) |
| 5 | **MediaPipe Face Mesh** | 468 landmarks, head pose | Low-medium | No — only 10 FPS, more than we need |
| 6 | **YOLOv8n face** | Modern architecture | High | No — 470ms per frame, way too slow |
| 7 | **Pi 5 + Hailo-8L** | 13 TOPS, transforms everything | $$ hardware | Future — when Pi 4 limits bite |

---

## Recommendation

**Don't change the detection model.** YuNet is already the right choice. The pipeline we built today (YuNet + MOSSE + dead zone + tuned parameters) is close to optimal for Pi 4.

**One architectural improvement worth doing:** restructure the detection loop to run YuNet on the full frame FIRST (not inside a person ROI), and only fall back to TFLite person detection when no face is found for >2 seconds. This would:
- Skip TFLite entirely when Alice's face is visible (most of the time)
- Run YuNet at ~25 FPS on full 640x480 (vs ~10 FPS through TFLite → ROI → YuNet)
- Keep TFLite as a body-tracking fallback for "Alice turned away" scenarios

**Hardware upgrade path:** When the Pi 4 becomes the bottleneck, a Pi 5 ($80) + Hailo-8L AI HAT+ ($70) would give 13 TOPS — enough to run SCRFD or even YOLOv8n at real-time speeds. But this is a future purchase, not needed now.

---

## Sources
- [Q-engineering Face Detection Benchmark (Pi 4)](https://github.com/Qengineering/Face-detection-Raspberry-Pi-32-64-bits)
- [LearnOpenCV: Face Detection Ultimate Guide 2025](https://learnopencv.com/what-is-face-detection-the-ultimate-guide/)
- [OpenCV: Cascade Classifier vs YuNet](https://opencv.org/blog/opencv-face-detection-cascade-classifier-vs-yunet/)
- [YuNet Paper (ICLR)](https://link.springer.com/content/pdf/10.1007/s11633-023-1423-y.pdf)
- [SCRFD Paper (InsightFace)](https://www.insightface.ai/research/scrfd)
- [MediaPipe for Raspberry Pi (Google)](https://developers.googleblog.com/mediapipe-for-raspberry-pi-and-ios/)
- [PyTorch Real-Time Inference on RPi](https://docs.pytorch.org/tutorials/intermediate/realtime_rpi.html)
- [Pi 5 Hailo-8L Benchmarks](https://community.hailo.ai/t/raspberry-pi-5-with-hailo-8l-benchmark/746)
- [pageauc/face-track-demo](https://github.com/pageauc/face-track-demo)
- [JennaSys/facetrack (pigpio smooth PWM)](https://github.com/JennaSys/facetrack)
- [PyImageSearch Pan/Tilt Tracking](https://pyimagesearch.com/2019/04/01/pan-tilt-face-tracking-with-a-raspberry-pi-and-opencv/)
