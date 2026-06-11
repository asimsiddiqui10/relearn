# Frontend

Next.js (App Router) + React 19 + Tailwind 4 + shadcn-pattern components.
Fonts: Inter (UI) + EB Garamond (headings/prose). Talks only to the backend
gateway (`NEXT_PUBLIC_API_URL`).

```
src/
  app/                  routes: /login /signup /(app)/spaces[/id[/documents/docId]]
  contexts/AuthContext  JWT in localStorage; Bearer on every request (Mike's pattern)
  lib/api.ts            typed gateway client
  lib/pdf.ts            pdfjs-dist loader (worker served from /public)
  components/ui/         button, input, card, spinner (shadcn pattern, ours)
  components/visualizer/ DocumentVisualizer + PdfPage (clean-room, spec/11)
  components/StructureTree, UploadCard, StatusBadge
  hooks/useIngestStatus  polls ingest status until terminal
```

## Visualizer (spec/11)
Clean-room build: virtualized pages (±1 via IntersectionObserver), canvas at
devicePixelRatio (retina-crisp), SVG highlight overlay in **raw Marker
coordinates** (`viewBox` = page Marker dims, `preserveAspectRatio="none"`),
ResizeObserver re-layout, explicit `loading→ready→error` states, and a
missing-page-dimensions degrade path (render PDF, disable highlights). Phase 0
renders no highlights — the overlay + `highlights` prop are wired for Phase 1.

## Dev
```bash
cp .env.local.example .env.local
pnpm install     # postinstall copies the pdf worker into /public
pnpm dev         # http://localhost:3000
```
