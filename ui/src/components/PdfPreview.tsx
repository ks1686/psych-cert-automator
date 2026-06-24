import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
declare global {
  var pdfjsLib: any;
}

interface PdfPreviewProps {
  pdfBytes: Uint8Array | null;
}

export function PdfPreview({ pdfBytes }: PdfPreviewProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [status, setStatus] = useState<"loading" | "error" | "empty" | "ready">(
    "loading",
  );

  useEffect(() => {
    if (!pdfBytes || pdfBytes.length === 0) {
      setStatus("empty");
      return;
    }

    setStatus("loading");

    let cancelled = false;

    (async () => {
      try {
        if (!window.pdfjsLib) {
          await loadScript("/pdfjs/pdf.min.js");
          if (!window.pdfjsLib) throw new Error("pdf.js failed to load");
          window.pdfjsLib.GlobalWorkerOptions.workerSrc =
            "/pdfjs/pdf.worker.min.js";
        }

        const pdf = await window.pdfjsLib.getDocument({ data: pdfBytes })
          .promise;
        const page = await pdf.getPage(1);
        const canvas = canvasRef.current;
        if (!canvas || cancelled) return;

        const scale = 1.5;
        const viewport = page.getViewport({ scale });
        canvas.height = viewport.height;
        canvas.width = viewport.width;

        const ctx = canvas.getContext("2d")!;
        await page.render({ canvasContext: ctx, viewport }).promise;
        if (!cancelled) setStatus("ready");
      } catch {
        if (!cancelled) setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [pdfBytes]);

  if (status === "empty") {
    return (
      <div className="flex items-center justify-center p-8 text-muted-foreground text-sm">
        No preview available
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="flex items-center justify-center p-8 text-destructive text-sm">
        Failed to render preview
      </div>
    );
  }

  return (
    <div className="relative flex items-center justify-center">
      {status === "loading" && (
        <div className="absolute inset-0 flex items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          <span className="ml-2 text-sm text-muted-foreground">
            Loading preview...
          </span>
        </div>
      )}
      <canvas
        ref={canvasRef}
        className="max-w-full"
        style={{ visibility: status === "ready" ? "visible" : "hidden" }}
      />
    </div>
  );
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(script);
  });
}
