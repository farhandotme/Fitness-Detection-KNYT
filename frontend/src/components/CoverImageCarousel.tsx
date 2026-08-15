import React, { useEffect, useRef, useState } from "react";

interface CoverImageCarouselProps {
  images: string[];
  alt: string;
  imgClassName?: string;
  /** 0 disables autoplay. */
  autoPlayMs?: number;
  showDots?: boolean;
  dotsClassName?: string;
  activeDotClassName?: string;
  inactiveDotClassName?: string;
}

/**
 * A small, dependency-free swipeable carousel: drag/swipe with the finger
 * or mouse to slide between images, with a smooth spring-like snap and
 * (optional) autoplay. Built for event cover/advertising banners, which
 * only ever hold up to a handful of images, so it deliberately skips
 * anything heavier (virtualization, lazy loading, etc).
 */
export function CoverImageCarousel({
  images,
  alt,
  imgClassName = "",
  autoPlayMs = 5000,
  showDots = true,
  dotsClassName = "absolute bottom-4 left-1/2 -translate-x-1/2 z-10 flex items-center gap-1.5",
  activeDotClassName = "w-6 bg-primary",
  inactiveDotClassName = "w-1.5 bg-white/50",
}: CoverImageCarouselProps) {
  const count = images.length;
  const [index, setIndex] = useState(0);
  const [dragPx, setDragPx] = useState(0);
  const [dragging, setDragging] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const dragStartRef = useRef<{ x: number; width: number } | null>(null);
  const hadDragRef = useRef(false);

  // A new set of images (different event, or images edited) always starts
  // back at the first slide.
  useEffect(() => {
    setIndex(0);
  }, [images.join("|")]);

  useEffect(() => {
    if (count <= 1 || dragging || !autoPlayMs) return;
    const id = setInterval(() => setIndex((i) => (i + 1) % count), autoPlayMs);
    return () => clearInterval(id);
  }, [count, dragging, autoPlayMs]);

  const goTo = (i: number) => setIndex(((i % count) + count) % count);

  const onPointerDown = (e: React.PointerEvent) => {
    if (count <= 1) return;
    const width = containerRef.current?.getBoundingClientRect().width ?? 1;
    dragStartRef.current = { x: e.clientX, width };
    hadDragRef.current = false;
    setDragging(true);
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragStartRef.current) return;
    const dx = e.clientX - dragStartRef.current.x;
    if (Math.abs(dx) > 6) hadDragRef.current = true;
    setDragPx(dx);
  };

  const endDrag = () => {
    if (!dragStartRef.current) {
      setDragging(false);
      return;
    }
    const { width } = dragStartRef.current;
    const threshold = width * 0.18;
    if (dragPx > threshold) goTo(index - 1);
    else if (dragPx < -threshold) goTo(index + 1);
    dragStartRef.current = null;
    setDragPx(0);
    setDragging(false);
  };

  // Swallow the click that follows a real drag so a swipe over a card
  // wrapped in a <Link> doesn't also trigger navigation.
  const onClickCapture = (e: React.MouseEvent) => {
    if (hadDragRef.current) {
      e.preventDefault();
      e.stopPropagation();
      hadDragRef.current = false;
    }
  };

  if (count === 0) return null;

  const slideWidthPercent = 100 / count;
  const dragPercent = dragStartRef.current
    ? (dragPx / (dragStartRef.current.width * count)) * 100
    : 0;
  const translatePercent = index * slideWidthPercent - dragPercent;

  return (
    <div
      ref={containerRef}
      className="relative w-full h-full overflow-hidden select-none"
      style={{ touchAction: count > 1 ? "pan-y" : undefined }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerLeave={endDrag}
      onPointerCancel={endDrag}
      onClickCapture={onClickCapture}
    >
      <div
        className="flex h-full"
        style={{
          width: `${count * 100}%`,
          transform: `translateX(-${translatePercent}%)`,
          transition: dragging
            ? "none"
            : "transform 600ms cubic-bezier(0.22, 1, 0.36, 1)",
        }}
      >
        {images.map((src, i) => (
          <div
            key={i}
            style={{ width: `${slideWidthPercent}%` }}
            className="h-full shrink-0"
          >
            <img
              src={src}
              alt={alt}
              draggable={false}
              className={`w-full h-full object-cover ${imgClassName}`}
            />
          </div>
        ))}
      </div>

      {showDots && count > 1 && (
        <div className={dotsClassName}>
          {images.map((_, i) => (
            <button
              key={i}
              type="button"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                goTo(i);
              }}
              aria-label={`Show image ${i + 1}`}
              className={`h-1.5 rounded-full transition-all ${
                i === index ? activeDotClassName : inactiveDotClassName
              }`}
            />
          ))}
        </div>
      )}
    </div>
  );
}
