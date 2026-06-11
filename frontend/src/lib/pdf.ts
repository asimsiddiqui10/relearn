"use client";

import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy } from "pdfjs-dist";

// Worker is copied to /public by the copy-pdf-worker script (pinned to the
// installed pdfjs-dist version, so it never drifts from the API).
if (typeof window !== "undefined") {
  pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
}

export async function loadPdf(url: string): Promise<PDFDocumentProxy> {
  return pdfjs.getDocument({ url }).promise;
}

export type { PDFDocumentProxy };
