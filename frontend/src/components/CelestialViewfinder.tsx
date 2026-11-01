import { API_ORIGIN } from "../api";
import { JobAction, isActiveJob } from "../jobAction";
import { useRef, useState, useEffect } from "react";
import { Button } from "./ui/Button";
import {
  RotateCcw,
  Sparkles,
  FolderOpen,
  Loader2,
  Minus,
  Plus,
  Square,
} from "lucide-react";
import { Crosshair } from "lucide-react";

interface Point {
  x: number;
  y: number;
}

export interface CelestialViewfinderProps {
  rawNoiseReduction?: boolean;
  sortByTime?: boolean;
  imageSrc?: string;
  livePreviewSrc?: string;
  files: string[];
  gapCount: number;
  polaris?: Point | null;
  onSetPolaris: (p: Point | null) => void;
  refStar2?: Point | null;
  onSetRefStar2: (p: Point) => void;
  inputDir?: string;
  onBrowseFolder?: () => void;
  isProcessing?: boolean;
  onDetectionActivityChange?: (active: boolean) => void;
}

export const CelestialViewfinder: React.FC<CelestialViewfinderProps> = ({
  rawNoiseReduction = true,
  sortByTime = true,
  imageSrc,
  livePreviewSrc,
  files,
  gapCount,
  polaris,
  onSetPolaris,
  refStar2,
  onSetRefStar2,
  inputDir,
  onBrowseFolder,
  isProcessing = false,
  onDetectionActivityChange,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });

  const [mode, setMode] = useState<"polaris" | "ref2">("polaris");
  const [isDetecting, setIsDetecting] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [detectNotice, setDetectNotice] = useState("");
  const [detectConfidence, setDetectConfidence] = useState<number | null>(null);
  const [detectedStars, setDetectedStars] = useState<Point[]>([]);
  const [detectedImage, setDetectedImage] = useState<string | null>(null);

  const [activeImage, setActiveImage] = useState<string | null>(null);
  const [imgLoaded, setImgLoaded] = useState(0);
  const [imageError, setImageError] = useState("");
  const [detectError, setDetectError] = useState("");
  const [viewport, setViewport] = useState({ width: 0, height: 0 });

  const imageElementRef = useRef<HTMLImageElement | null>(null);
  const liveImageElementRef = useRef<HTMLImageElement | null>(null);
  const detectActionRef = useRef<JobAction | null>(null);

  const currentImage = activeImage || imageSrc;
  const showingLivePreview = Boolean(isProcessing && livePreviewSrc && liveImageElementRef.current);

  useEffect(() => {
    detectActionRef.current?.dispose();
    detectActionRef.current = null;
    setIsDetecting(false);
    setIsCancelling(false);
    setDetectNotice("");
    setActiveImage(null);
    setDetectConfidence(null);
    setDetectedStars([]);
    setDetectedImage(null);
    setImageError("");
    setDetectError("");
    return () => {
      detectActionRef.current?.dispose();
      detectActionRef.current = null;
    };
  }, [imageSrc, rawNoiseReduction, sortByTime]);
  useEffect(() => {
    onDetectionActivityChange?.(isDetecting);
    return () => onDetectionActivityChange?.(false);
  }, [isDetecting, onDetectionActivityChange]);
  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;
    const observer = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      setViewport({ width, height });
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  // Load image
  useEffect(() => {
    if (currentImage) {
      imageElementRef.current = null;
      setImgLoaded(0);
      const img = new Image();
      setImageError("");
      img.onload = () => {
        imageElementRef.current = img;
        setImgLoaded((prev) => prev + 1);
        handleResetView(img);
      };
      img.onerror = () => {
        imageElementRef.current = null;
        setImageError(
          "This frame could not be previewed. Check the local image service or choose another frame.",
        );
        setImgLoaded(0);
      };
      img.src = currentImage;
      return () => {
        img.onload = null;
        img.onerror = null;
      };
    } else {
      imageElementRef.current = null;
      setImgLoaded(0);
    }
  }, [currentImage]);

  useEffect(() => {
    liveImageElementRef.current = null;
    if (!livePreviewSrc) return;
    const img = new Image();
    img.onload = () => {
      liveImageElementRef.current = img;
      setImgLoaded((prev) => prev + 1);
    };
    img.onerror = () => { liveImageElementRef.current = null; };
    img.src = livePreviewSrc;
    return () => { img.onload = null; img.onerror = null; };
  }, [livePreviewSrc]);

  const handleResetView = (imgOverride?: HTMLImageElement) => {
    const img = imgOverride || imageElementRef.current;
    if (img && containerRef.current) {
      const rect = containerRef.current.getBoundingClientRect();
      // Toolbar and filmstrip live outside the canvas; fit within its own bounds.
      const availableHeight = Math.max(100, rect.height - 24);
      const scaleX = (rect.width - 24) / img.width;
      const scaleY = availableHeight / img.height;
      const fitScale = Math.min(scaleX, scaleY) * 0.92;
      setScale(fitScale);
      setOffset({
        x: (rect.width - img.width * fitScale) / 2,
        y: 12 + (availableHeight - img.height * fitScale) / 2,
      });
    } else {
      setScale(1);
      setOffset({ x: 0, y: 0 });
    }
  };

  const handleAutoDetect = async () => {
    if (isProcessing || detectActionRef.current?.active) return;
    if (!inputDir) {
      setDetectError("Load a sequence before detecting stars.");
      return;
    }
    setDetectError("");
    setDetectNotice("");
    setDetectConfidence(null);
    const action = new JobAction(API_ORIGIN, (state) => {
      if (detectActionRef.current !== action) return;
      setIsDetecting(isActiveJob(state));
      setIsCancelling(state.status === "cancelling");
      setDetectError(state.error || "");
      if (state.status === "cancelled") setDetectNotice("Star detection cancelled.");
    });
    detectActionRef.current = action;
    const state = await action.start("/api/stars/detect/start", {
      path: inputDir, frame_step: 10, raw_noise_reduction: rawNoiseReduction,
      sort_by_time: sortByTime,
    });
    if (detectActionRef.current !== action) return;
    if (state.status === "completed" && state.result) {
        const data = state.result;
        // Matched stars are references, not an identification of Polaris.
        onSetPolaris(null);
        const referenceImage = data.reference_image
          ? `${API_ORIGIN}/api/images/preview?path=${encodeURIComponent(data.reference_image)}`
          : imageSrc || null;
        setActiveImage(referenceImage);
        setDetectedImage(referenceImage);
        setDetectedStars((data.reference_stars || []).map(([x, y]: number[]) => ({ x, y })));
        if (data.second_star)
          onSetRefStar2({ x: data.second_star[0], y: data.second_star[1] });
        setDetectConfidence(data.confidence);
    }
  };

  useEffect(() => {
    if (imageElementRef.current) handleResetView();
  }, [viewport.width, viewport.height]);

  // Canvas drawing
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !containerRef.current) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // Resize canvas to match container
    const rect = containerRef.current.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // Clear with neutral deep background
    ctx.fillStyle = "#050505";
    ctx.fillRect(0, 0, rect.width, rect.height);

    // Subtle coordinate grid
    ctx.strokeStyle = "rgba(255, 255, 255, 0.035)";
    ctx.lineWidth = 1;
    for (let i = 0; i < rect.width; i += 80) {
      ctx.beginPath();
      ctx.moveTo(i, 0);
      ctx.lineTo(i, rect.height);
      ctx.stroke();
    }
    for (let j = 0; j < rect.height; j += 80) {
      ctx.beginPath();
      ctx.moveTo(0, j);
      ctx.lineTo(rect.width, j);
      ctx.stroke();
    }

    ctx.save();
    ctx.translate(offset.x, offset.y);
    ctx.scale(scale, scale);

    // Draw Image - never distorted or tinted
    const displayImage = showingLivePreview ? liveImageElementRef.current : imageElementRef.current;
    if (displayImage) {
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";
      ctx.drawImage(displayImage, 0, 0);
    } else {
      // Subtle background stars when no image
      ctx.fillStyle = "rgba(255, 255, 255, 0.4)";
      for (let i = 0; i < 80; i++) {
        const x = (Math.sin(i * 123) * 1000 + 1000) % 2000;
        const y = (Math.cos(i * 321) * 1000 + 1000) % 2000;
        ctx.beginPath();
        ctx.arc(x, y, (i % 3) * 0.8 + 0.6, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // Connecting Vector Line between Polaris and Second Reference Star
    if (polaris && refStar2) {
      ctx.strokeStyle = "rgba(255, 255, 255, 0.6)";
      ctx.lineWidth = 1.5 / scale;
      ctx.setLineDash([8 / scale, 6 / scale]);
      ctx.beginPath();
      ctx.moveTo(polaris.x, polaris.y);
      ctx.lineTo(refStar2.x, refStar2.y);
      ctx.stroke();
      ctx.setLineDash([]);

      const dx = refStar2.x - polaris.x;
      const dy = refStar2.y - polaris.y;
      const angle = ((Math.atan2(dy, dx) * 180) / Math.PI + 360) % 360;

      ctx.fillStyle = "#ffffff";
      ctx.font = `600 ${13 / scale}px monospace`;
      const midX = (polaris.x + refStar2.x) / 2;
      const midY = (polaris.y + refStar2.y) / 2;
      ctx.fillText(
        `${angle.toFixed(2)}°`,
        midX + 10 / scale,
        midY - 10 / scale,
      );
    }

    // Reticle rendering (Cyan for Polaris, Amber for Ref Star 2)
    const drawReticle = (p: Point, color: string, label: string) => {
      ctx.strokeStyle = color;
      ctx.lineWidth = 2 / scale;
      const size = 28 / scale;
      const innerSize = 9 / scale;

      // Crosshair
      ctx.beginPath();
      ctx.moveTo(p.x - size, p.y);
      ctx.lineTo(p.x - innerSize, p.y);
      ctx.moveTo(p.x + innerSize, p.y);
      ctx.lineTo(p.x + size, p.y);
      ctx.moveTo(p.x, p.y - size);
      ctx.lineTo(p.x, p.y - innerSize);
      ctx.moveTo(p.x, p.y + innerSize);
      ctx.lineTo(p.x, p.y + size);
      ctx.stroke();

      // Center dot
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 2.5 / scale, 0, Math.PI * 2);
      ctx.fill();

      // Outer Target Ring
      ctx.beginPath();
      ctx.arc(p.x, p.y, size * 0.75, 0, Math.PI * 2);
      ctx.stroke();

      // Label with background pill for contrast
      ctx.font = `600 ${11 / scale}px monospace`;
      const text = `${label} [${p.x.toFixed(1)}, ${p.y.toFixed(1)}]`;
      ctx.fillStyle = "rgba(5, 5, 5, 0.75)";
      ctx.fillRect(
        p.x + size + 4 / scale,
        p.y - 18 / scale,
        (text.length * 7 + 8) / scale,
        16 / scale,
      );

      ctx.fillStyle = color;
      ctx.fillText(text, p.x + size + 8 / scale, p.y - 6 / scale);
    };

    if (!showingLivePreview && currentImage === detectedImage) {
      detectedStars.forEach((star, index) => {
        ctx.strokeStyle = "#34d399";
        ctx.lineWidth = 1 / scale;
        ctx.beginPath();
        ctx.arc(star.x, star.y, 7 / scale, 0, Math.PI * 2);
        ctx.stroke();
        if (index < 3) drawReticle(star, "#34d399", `STAR ${index + 1}`);
      });
    }
    if (!showingLivePreview && polaris) drawReticle(polaris, "#38bdf8", "POLARIS");
    if (!showingLivePreview && refStar2) drawReticle(refStar2, "#f59e0b", "REF STAR");

    ctx.restore();
  }, [scale, offset, polaris, refStar2, imgLoaded, viewport, detectedStars, currentImage, detectedImage, showingLivePreview]);

  const zoomAtCenter = (factor: number) => {
    if (!containerRef.current || !imageElementRef.current) return;
    const { width, height } = containerRef.current.getBoundingClientRect();
    const next = Math.min(50, Math.max(0.01, scale * factor));
    setOffset({
      x: width / 2 - ((width / 2 - offset.x) / scale) * next,
      y: height / 2 - ((height / 2 - offset.y) / scale) * next,
    });
    setScale(next);
  };

  // Handlers for Pan & Zoom
  const handleWheel = (e: React.WheelEvent) => {
    if (!imageElementRef.current) return;
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();

    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const imgX = (mouseX - offset.x) / scale;
    const imgY = (mouseY - offset.y) / scale;

    const zoomFactor = -e.deltaY * 0.001;
    let newScale = scale * (1 + zoomFactor);
    newScale = Math.max(0.05, Math.min(newScale, 50));

    setScale(newScale);
    setOffset({
      x: mouseX - imgX * newScale,
      y: mouseY - imgY * newScale,
    });
  };

  const handleMouseDown = (e: React.PointerEvent) => {
    if (isProcessing || isDetecting) return;
    if (!imageElementRef.current) return;
    if (e.button === 1 || e.button === 2 || e.shiftKey) {
      setIsDragging(true);
      setDragStart({ x: e.clientX - offset.x, y: e.clientY - offset.y });
    } else {
      if (currentImage !== imageSrc) {
        setDetectError("Select the first frame before placing manual reference stars.");
        return;
      }
      // Left click to place reticle
      if (!containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const x = (e.clientX - rect.left - offset.x) / scale;
      const y = (e.clientY - rect.top - offset.y) / scale;

      const img = imageElementRef.current;
      if (x < 0 || y < 0 || x >= img.width || y >= img.height) return;
      setDetectConfidence(null);
      setDetectedStars([]);
      if (mode === "ref2") {
        onSetRefStar2({ x, y });
      } else {
        onSetPolaris({ x, y });
      }
    }
  };

  const handleMouseMove = (e: React.PointerEvent) => {
    if (isDragging) {
      setOffset({
        x: e.clientX - dragStart.x,
        y: e.clientY - dragStart.y,
      });
    }
  };

  const handleMouseUp = () => setIsDragging(false);

  return (
    <div className="viewfinder glass-surface">
      {/* Top Floating Glass Toolbar */}
      <div className="viewfinder-toolbar">
        {/* Left Toolbar Capsule */}
        <div className="glass-surface glass-nav flex items-center gap-1.5 p-1 pointer-events-auto shadow-[0_4px_16px_rgba(0,0,0,0.3)]">
          <Button
            variant="secondary"
            active={mode === "polaris"}
            onClick={() => setMode("polaris")}
            className={`!min-h-[32px] !px-3 text-xs ${mode === "polaris" ? "!text-sky-300" : ""}`}
            aria-pressed={mode === "polaris"}
          >
            <span
              className="w-2 h-2 rounded-full bg-sky-400 mr-1.5"
              aria-hidden="true"
            />
            Polaris
          </Button>

          <Button
            variant="secondary"
            active={mode === "ref2"}
            onClick={() => setMode("ref2")}
            className={`!min-h-[32px] !px-3 text-xs ${mode === "ref2" ? "!text-amber-300" : ""}`}
            aria-pressed={mode === "ref2"}
          >
            <span
              className="w-2 h-2 rounded-full bg-amber-400 mr-1.5"
              aria-hidden="true"
            />
            Ref Star
          </Button>

          <div className="w-[1px] h-4 bg-white/10 mx-0.5" />

          <Button
            variant="secondary"
            onClick={() => handleResetView()}
            className="!min-h-[32px] !px-2.5 text-xs text-slate-300 hover:text-white"
            title="Reset pan and zoom"
          >
            <RotateCcw className="w-3.5 h-3.5 mr-1" aria-hidden="true" />
            Reset
          </Button>

          <Button
            variant="quiet"
            onClick={() => zoomAtCenter(1 / 1.2)}
            disabled={!currentImage}
            aria-label="Zoom out"
            className="zoom-button"
          >
            <Minus size={13} />
          </Button>
          <Button
            variant="quiet"
            onClick={() => zoomAtCenter(1.2)}
            disabled={!currentImage}
            aria-label="Zoom in"
            className="zoom-button"
          >
            <Plus size={13} />
          </Button>
          <span className="field-well px-2 py-0.5 text-xs font-mono text-slate-300 tabular-nums border border-white/10">
            {(scale * 100).toFixed(0)}%
          </span>
        </div>

        {/* Right Toolbar Capsule: Auto-detect */}
        <div className="glass-surface glass-nav flex items-center gap-2 p-1 pointer-events-auto shadow-[0_4px_16px_rgba(0,0,0,0.3)]">
          <Button
            variant="secondary"
            onClick={isDetecting ? () => detectActionRef.current?.cancel() : handleAutoDetect}
            disabled={isCancelling || (!isDetecting && (isProcessing || !inputDir || !imageSrc))}
            className={`!min-h-[32px] !px-3 text-xs font-semibold text-slate-200 hover:text-white ${isDetecting ? "action-cancel" : ""}`}
          >
            {isCancelling ? (
              <>
                <Loader2
                  className="w-3.5 h-3.5 animate-spin mr-1.5 text-slate-300"
                  aria-hidden="true"
                />
                Cancelling…
              </>
            ) : isDetecting ? (
              <><Square className="w-3.5 h-3.5 mr-1.5" aria-hidden="true" />Cancel detection</>
            ) : (
              <>
                <Sparkles
                  className="w-3.5 h-3.5 mr-1.5 text-slate-300"
                  aria-hidden="true"
                />
                Detect references
              </>
            )}
          </Button>

          {detectConfidence !== null && (
            <span className="field-well px-2.5 py-1 text-xs font-mono text-slate-200 border border-white/10">
              {(detectConfidence * 100).toFixed(1)}%
            </span>
          )}
        </div>
      </div>

      {/* Interactive Celestial Canvas */}
      <div
        ref={containerRef}
        className="canvas-stage"
        onWheel={handleWheel}
        tabIndex={currentImage ? 0 : -1}
        role="img"
        aria-label={showingLivePreview
          ? "Live aligned star trail preview. Reference selection is paused while alignment runs."
          : "Reference star image. Click to place the selected reference. Use plus or minus to zoom and arrow keys to pan."}
        onKeyDown={(e) => {
          if (e.key === "+" || e.key === "=") {
            e.preventDefault();
            zoomAtCenter(1.2);
          }
          if (e.key === "-") {
            e.preventDefault();
            zoomAtCenter(1 / 1.2);
          }
          if (
            ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)
          ) {
            e.preventDefault();
            setOffset((previous) => ({
              x:
                previous.x +
                (e.key === "ArrowLeft" ? 24 : e.key === "ArrowRight" ? -24 : 0),
              y:
                previous.y +
                (e.key === "ArrowUp" ? 24 : e.key === "ArrowDown" ? -24 : 0),
            }));
          }
        }}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          handleMouseDown(e);
        }}
        onPointerMove={handleMouseMove}
        onPointerUp={handleMouseUp}
        onPointerCancel={handleMouseUp}
        onContextMenu={(e) => e.preventDefault()}
      >
        <canvas ref={canvasRef} className="block w-full h-full" />
        {showingLivePreview && (
          <div className="live-preview-badge" role="status">
            <span className="live-preview-pulse" aria-hidden="true" />
            Live trails · {" "} {isProcessing ? "building from aligned frames" : "preview"}
          </div>
        )}

        {!currentImage && (
          <div className="viewfinder-empty">
            <img className="empty-app-icon" src={`${import.meta.env.BASE_URL}app-icon.svg`} alt="" width={88} height={88} />
            <p className="eyebrow">FROM FIRST FRAME TO FINAL STACK</p>
            <h2>
              A whole night.
              <br />
              <span>One clear picture.</span>
            </h2>
            <p>
              Load your night-sky sequence, set your reference stars,
              <br className="desktop-break" /> and bring every frame into
              alignment.
            </p>
            {onBrowseFolder && (
              <Button onClick={onBrowseFolder}>
                <FolderOpen size={15} />
                Choose image folder
              </Button>
            )}
            <span className="empty-formats">JPEG · PNG · TIFF · RAW</span>
          </div>
        )}
        {imageError && (
          <div className="image-error" role="alert">
            {imageError}
          </div>
        )}
      </div>
      <div className="reference-guide">
        <Crosshair size={13} aria-hidden="true" />
        <span>
          {detectedStars.length > 0
            ? `${detectedStars.length} stars matched. Automatic alignment preserves trails without Polaris.`
            : polaris
            ? refStar2
              ? "Both references selected. Your sequence is ready to align."
              : "Polaris selected. Add a reference star for rotation correction."
            : currentImage
              ? "Stars are matched automatically when you start. Polaris is optional."
              : "Load frames to start selecting references."}
        </span>
        <span className="pan-hint">Scroll to zoom · Shift-drag to pan</span>
      </div>
      {detectError && (
        <p className="inline-error detection-error" role="alert">
          {detectError}
        </p>
      )}
      {detectNotice && <p className="detection-error" role="status">{detectNotice}</p>}

      {/* Filmstrip Reel at bottom */}
      <div className="filmstrip">
        <div className="text-[11px] text-slate-400 font-mono mb-1.5 flex justify-between px-1 select-text">
          <span className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
            {files.length
              ? `${files.length} FRAMES${gapCount ? ` · ${gapCount} GAPS` : ""}`
              : "YOUR FRAME SEQUENCE"}
          </span>
          <span>
            {files.length
              ? `Frame ${Math.max(1, files.findIndex((file) => currentImage?.includes(encodeURIComponent(file))) + 1)} / ${files.length}`
              : "No frames loaded"}
          </span>
        </div>
        <div className="flex-1 flex gap-2 overflow-x-auto custom-scroll pb-1">
          {files.length > 0
            ? files.map((file, i) => {
                const previewUrl = `${API_ORIGIN}/api/images/preview?path=${encodeURIComponent(file)}`;
                const isActive = currentImage === previewUrl;
                return (
                  <button
                    type="button"
                    aria-label={`View frame ${i + 1}`}
                    aria-pressed={isActive}
                    key={file}
                    onClick={() => setActiveImage(previewUrl)}
                    className={`min-w-[4.2rem] h-full bg-[#050505] rounded-lg cursor-pointer transition-all flex items-center justify-center overflow-hidden border ${
                      isActive
                        ? "border-slate-300 ring-1 ring-white/25"
                        : "border-white/10 hover:border-white/25"
                    }`}
                    title={file}
                  >
                    <img
                      src={`${previewUrl}&max_size=256`}
                      alt=""
                      loading="lazy"
                      className="w-full h-full object-cover"
                    />
                  </button>
                );
              })
            : // Placeholder reel
              [...Array(10)].map((_, i) => (
                <div
                  key={i}
                  className="min-w-[4.2rem] h-full bg-[#0a0a0a] border border-white/5 rounded-lg flex items-center justify-center text-[10px] text-slate-600 font-mono select-none"
                >
                  {i.toString().padStart(4, "0")}
                </div>
              ))}
        </div>
      </div>
    </div>
  );
};
