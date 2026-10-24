"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Copy } from "lucide-react";

type CopyState = "idle" | "busy" | "done" | "failed";

/** Shared copy-to-clipboard button with busy / "copied" success / failure states. */
export default function CopyButton({
  text,
  label,
  copiedLabel,
  failedLabel,
}: {
  text: string;
  /** Caption before copying (defaults to detail.copy). */
  label?: string;
  /** Caption after a successful copy (defaults to detail.copied). */
  copiedLabel?: string;
  /** Caption when the clipboard write is rejected (defaults to detail.copyFailed). */
  failedLabel?: string;
}) {
  const { t } = useTranslation();
  const [state, setState] = useState<CopyState>("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Clear the pending "back to idle" timer when unmounting.
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    []
  );

  async function copy() {
    if (timer.current) clearTimeout(timer.current);
    setState("busy");
    try {
      await navigator.clipboard.writeText(text);
      setState("done");
    } catch {
      setState("failed");
    }
    timer.current = setTimeout(() => setState("idle"), 1200);
  }

  const caption =
    state === "done"
      ? (copiedLabel ?? t("detail.copied"))
      : state === "failed"
        ? (failedLabel ?? t("detail.copyFailed"))
        : (label ?? t("detail.copy"));

  return (
    <button className="ghost copy-btn" disabled={state === "busy"} onClick={() => void copy()}>
      {state === "done" ? <Check size={13} /> : <Copy size={13} />} {caption}
    </button>
  );
}
