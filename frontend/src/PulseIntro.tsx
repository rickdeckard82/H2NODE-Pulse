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

        {/* Brand name */}
        <div className="pulse-intro-brand">
          <span className="pulse-intro-title-pulse">H2NODE</span>
          <span className="pulse-intro-title-services">Pulse</span>
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
