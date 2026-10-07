import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

interface PdfViewport {
  readonly height: number;
  readonly width: number;
}

interface PdfRenderTask {
  readonly promise: Promise<void>;
}

interface PdfPage {
  getViewport(options: { readonly scale: number }): PdfViewport;
  render(options: {
    readonly canvasContext: CanvasRenderingContext2D;
    readonly viewport: PdfViewport;
  }): PdfRenderTask;
}

interface PdfDocument {
  getPage(pageNumber: number): Promise<PdfPage>;
}

interface PdfLoadingTask {
  readonly promise: Promise<PdfDocument>;
}

interface PdfJsLib {
  readonly GlobalWorkerOptions: {
    workerSrc: string;
  };
  getDocument(source: { readonly data: Uint8Array }): PdfLoadingTask;
}

declare global {
  interface Window {
    pdfjsLib?: PdfJsLib;
  }
}

interface PdfPreviewProps {
  pdfBytes: Uint8Array | null;
}

export function PdfPreview({ pdfBytes }: PdfPreviewProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [status, setStatus] = useState<"loading" | "error" | "empty" | "ready">(
    "loading",
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!pdfBytes || pdfBytes.length === 0) {
      setStatus("empty");
      return;
    }

    setStatus("loading");

    let cancelled = false;

    (async () => {
      try {
        const pdfJs = await ensurePdfJs();
        // pdf.js transfers this buffer to its worker. Copy first so a remount
        // (React strict mode, or opening preview again) still has the bytes.
        const pdf = await pdfJs.getDocument({ data: pdfBytes.slice() }).promise;
        const page = await pdf.getPage(1);
        const canvas = canvasRef.current;
        if (!canvas || cancelled) return;

        const scale = 1.5;
        const viewport = page.getViewport({ scale });
        canvas.height = viewport.height;
        canvas.width = viewport.width;

        const ctx = canvas.getContext("2d");
        if (!ctx) throw new Error("Canvas 2D context unavailable");
        await page.render({ canvasContext: ctx, viewport }).promise;
        if (!cancelled) setStatus("ready");
      } catch (err) {
        if (!cancelled) {
          setErrorMessage(err instanceof Error ? err.message : "Preview failed");
          setStatus("error");
        }
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
        {errorMessage ? `: ${errorMessage}` : ""}
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
    const finish = () => resolve();
    const fail = () => reject(new Error(`Failed to load ${src}`));
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) {
      if (window.pdfjsLib) {
        finish();
        return;
      }
      existing.addEventListener("load", finish, { once: true });
      existing.addEventListener("error", fail, { once: true });
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.onload = finish;
    script.onerror = fail;
    document.head.appendChild(script);
  });
}

async function ensurePdfJs(): Promise<PdfJsLib> {
  const existingPdfJs = window.pdfjsLib;
  if (existingPdfJs) return existingPdfJs;

  await loadScript("/pdfjs/pdf.min.js");
  const loadedPdfJs = window.pdfjsLib;
  if (!loadedPdfJs) throw new Error("pdf.js failed to load");

  loadedPdfJs.GlobalWorkerOptions.workerSrc = "/pdfjs/pdf.worker.min.js";
  return loadedPdfJs;
}
