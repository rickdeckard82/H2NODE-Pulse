import { useEffect, useState } from "react";

export function PulseIntro({ onFinish }: { onFinish?: () => void }) {
  const [stage, setStage] = useState<"active" | "fading" | "done">("active");

  useEffect(() => {
    // If user prefers reduced motion or automated test runner, finish immediately
    const prefersReduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced || navigator.webdriver) {
      setStage("done");
      onFinish?.();
      return;
    }

    const fadeTimer = setTimeout(() => {
      setStage("fading");
    }, 1500);

    const doneTimer = setTimeout(() => {
      setStage("done");
      onFinish?.();
    }, 1950);

    const handleDismiss = () => {
      setStage("fading");
      setTimeout(() => {
        setStage("done");
        onFinish?.();
      }, 250);
    };

    window.addEventListener("keydown", handleDismiss, { once: true });
    window.addEventListener("pointerdown", handleDismiss, { once: true });

    return () => {
      clearTimeout(fadeTimer);
      clearTimeout(doneTimer);
      window.removeEventListener("keydown", handleDismiss);
      window.removeEventListener("pointerdown", handleDismiss);
    };
  }, [onFinish]);

  if (stage === "done") return null;

  return (
    <div
      className={`pulse-intro-overlay ${stage === "fading" ? "pulse-intro-fading" : ""}`}
      aria-hidden="true"
      role="presentation"
    >
      <div className="pulse-intro-content">
        {/* Expanding pulse ripple rings in background */}
        <div className="pulse-ripple-ring ring-1" />
        <div className="pulse-ripple-ring ring-2" />
        <div className="pulse-ripple-ring ring-3" />

        {/* Pulse emblem with ECG heartbeat wave */}
        <div className="pulse-intro-emblem">
          <svg
            viewBox="0 0 64 64"
            className="pulse-emblem-svg"
            width="64"
            height="64"
          >
            <defs>
              <linearGradient
                id="pulse-bg-gradient"
                x1="0%"
                y1="0%"
                x2="100%"
                y2="100%"
              >
                <stop offset="0%" stopColor="#1a4fd8" />
                <stop offset="100%" stopColor="#123ca1" />
              </linearGradient>
              <linearGradient
                id="pulse-ecg-gradient"
                x1="0%"
                y1="0%"
                x2="100%"
                y2="0%"
              >
                <stop offset="0%" stopColor="#93c5fd" />
                <stop offset="50%" stopColor="#ffffff" />
                <stop offset="100%" stopColor="#bfdbfe" />
              </linearGradient>
              <filter
                id="pulse-glow"
                x="-20%"
                y="-20%"
                width="140%"
                height="140%"
              >
                <feGaussianBlur stdDeviation="1.5" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>
            <rect
              width="64"
              height="64"
              rx="16"
              fill="url(#pulse-bg-gradient)"
            />
            {/* Signature ECG heartbeat line */}
            <path
              className="pulse-ecg-intro-path"
              d="M13 34 h9 l3.5 8 l5.5 -21 l4.5 16 l3 -5.5 h12.5"
              fill="none"
              stroke="url(#pulse-ecg-gradient)"
              strokeWidth="3.2"
              strokeLinecap="round"
              strokeLinejoin="round"
              filter="url(#pulse-glow)"
            />
          </svg>
        </div>

        {/* Brand name */}
        <div className="pulse-intro-brand">
          <span className="pulse-intro-title-pulse">pulse</span>
          <span className="pulse-intro-title-services">services</span>
        </div>

        {/* Dynamic heartbeat ECG track below name */}
        <div className="pulse-intro-track-wrapper">
          <svg
            viewBox="0 0 240 24"
            className="pulse-intro-track-svg"
            preserveAspectRatio="none"
          >
            <path
              className="pulse-track-bg"
              d="M0 12 h75 l4 -5 l4 10 l5 -15 l5 18 l4 -11 l4 5 h139"
              fill="none"
              stroke="#e2e8f0"
              strokeWidth="2"
            />
            <path
              className="pulse-track-live"
              d="M0 12 h75 l4 -5 l4 10 l5 -15 l5 18 l4 -11 l4 5 h139"
              fill="none"
              stroke="#174dcc"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <div className="pulse-track-dot" />
        </div>

        <p className="pulse-intro-subtitle">Suporte Interno · Tecnologia</p>
      </div>
    </div>
  );
}
