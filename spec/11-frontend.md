# Frontend

Stack and component architecture modeled on MikeOSS's frontend — **same libraries, our
own code** (MikeOSS is AGPL-3.0: using the identical open-source libraries is fine;
copying its component source is not). Responsive is a first-class requirement.

## Stack (matches Mike's choices where they make sense)

| Concern | Library | Note |
|---|---|---|
| Framework | Next.js (App Router) + React 19 | Same as Mike |
| Styling | Tailwind CSS 4 + tw-animate-css | Same as Mike |
| Components | shadcn/ui pattern — Radix primitives + cva + clsx + tailwind-merge | Mike hand-rolls the same pattern (`components/ui/`); shadcn gives it to us generated, ours to own |
| Icons | lucide-react | Same as Mike |
| Markdown | react-markdown + remark-gfm + **remark-math + rehype-katex** | KaTeX is non-negotiable for NEET/JEE content; Mike already proves this combo |
| PDF | pdfjs-dist (pinned version) | Visualizer canvas + our SVG overlay |
| Charts | recharts | Later — practice analytics, coverage views |
| Route progress | nextjs-toploader | Cheap polish, Mike uses it |
| Auth client | `react-oidc-context` (OIDC code+PKCE vs Cognito) + our AuthContext | Mike's *pattern* (context wrapper + Bearer JWT), Cognito as issuer (see Auth below) |
| Fonts | **Inter** (UI sans) + **EB Garamond** (serif) via `next/font/google` | Mike's exact pair: Inter for chrome/UI, EB Garamond for headings + assistant answer prose — the "document, not SaaS" feel |

Not adopted from Mike: Tiptap/md-editor (no document editing in MVP — revisit for
test-series editing), docx/mammoth/exceljs (artifact export is server-side), Cloudflare
OpenNext tooling (we deploy plain Next).

## App shell & routes

Mike's structural pattern, renamed to our domain (project → space):

```
/login /signup
/(app)/                     shell: left sidebar + main area + right panel
   spaces/                  space list (grid/cards) + create modal
   spaces/[id]/             space home: resources list, members, instructions/memory
   spaces/[id]/chat/[sid]   chat view (the core screen)
   workflows/               Phase 4
   account/
```

Contexts (Mike's pattern): `AuthContext`, `SidebarContext`, `ChatSessionsContext`.
Data/streaming hooks: `useAgentChat` (SSE reducer — see below), `useIngestStatus`,
`useSpace`, `useGenerateChatTitle` (small-model title after first turn, like Mike).

## The core screen: chat + visualizer

Desktop: two-pane. Left = chat column; right = collapsible **evidence panel** hosting the
PDF visualizer. Clicking a citation chip opens the right panel at doc/page and pulses the
bbox highlight. The panel remembers last doc/page per session.

### Chat block renderer (implements spec 04)

`useAgentChat` holds the SSE reducer; one component per block type:

- `<ThinkingBlock>` — collapsed shimmer, expandable
- `<ToolBlock>` — spinner+label → ✓ +summary+duration, updates in place
- `<TextBlock>` — streaming markdown (gfm + KaTeX), `[E#]` rendered as `<CitationChip>`
- `<ClarificationCard>` / `<ApprovalCard>` — inline HITL (options, approve/reject,
  preview list for save_questions)
- `<StepsSummary>` — post-run collapse: "Worked for 14s · 5 steps", expandable
- `<ConfidenceChip>`, `<FeedbackBar>` (thumbs + flag-citation per evidence block)
- `<TaskChecklist>` — background-run task list (`task_update` events, spec 10)

`<ChatInput>` — textarea with attach-resource scoping (`@resource` mentions later),
workflow selector (Phase 4), disabled states driven by run status.

### PDF visualizer (`<DocumentVisualizer>`) — built from scratch

No Mike equivalent (Mike's doc view is a Tiptap editor) and v1's component was buggy —
this is a clean-room build. Only two *ideas* carry over from v1: store raw Marker
coordinates; overlay with stretch-fit SVG.

**Core rendering**
- pdfjs-dist (pinned version + matching worker) renders one page per `<canvas>`.
- **Virtualized page list**: only visible pages (±1) render; large books stay smooth.
- Canvas rendered at `devicePixelRatio` scale, CSS-sized down — crisp on retina
  (classic blurry-PDF bug, prevented by spec).
- Render results cached per (page, zoom); page jumps don't re-render needlessly.

**Highlight layer**
- Absolutely-positioned SVG over each canvas. `viewBox` = that page's Marker dimensions
  (from `documents.metadata_json.page_dimensions`), `preserveAspectRatio="none"` —
  bbox/polygon drawn in raw Marker coordinates, zero client-side conversion. One
  coordinate space, ever.
- Highlight kinds: **active** (clicked citation: filled + outline + pulse-once
  animation, auto-scrolled into view) and **passive** (other evidence on the page:
  subtle tint). Overlapping highlights stack with blend, not occlusion.
- Polygon preferred when present; bbox fallback. Image evidence highlights the image
  region; question chunks (Pattern B, block-level bbox only) highlight the block.
- Click a highlight → `onHighlightClick(chunkId)` (chat scrolls to the citing block —
  reverse navigation).

**Navigation & viewport**
- Citation jump API: `show({docId, page, highlightIds})` → switch doc if needed → scroll
  to page → pulse active highlight.
- Zoom: fit-width (default) / fit-page / pinch & ctrl-scroll custom; page number input +
  prev/next; current page tracked via IntersectionObserver.
- `ResizeObserver`-driven re-layout: container resize, panel collapse/expand, and device
  rotation all re-render correctly at the new size (v1's primary bug class — explicit
  requirement, covered by fixture tests).

**States & errors**
- Explicit machine: `idle → loading → ready → error`; skeleton page placeholders while
  loading; distinct errors for fetch-failed, render-failed, and **missing page
  dimensions** (degrade: render PDF, disable highlights, log loudly — never silently
  misplace a highlight).

**Contract**
- Props in, events out: `{docId, initialPage, highlights[]}` in; `onHighlightClick`,
  `onPageChange` out. No data fetching inside the component; signed URL + geometry are
  passed down.
- Fixture suite: 3–4 known PDFs (single-column textbook, two-column question paper,
  scanned+OCR, image-heavy) with snapshot tests for highlight placement at multiple
  zooms/sizes.

**Mobile**: bottom-sheet presentation (see Responsive) — fit-width, active highlight
auto-centered, swipe between adjacent evidence pages.

## Auth (AWS Cognito — Mike's *shape*, AWS-only billing)

Constraint: pay only AWS. Cognito user pool (Lite tier: 10k MAU free, never pauses).

- **Frontend**: our own login/signup UI (our fonts/design — NOT Cognito's hosted UI).
  OIDC authorization-code + PKCE via `react-oidc-context` (lightweight; skip Amplify).
  `AuthContext` wrapper, Mike's pattern; every backend request carries
  `Authorization: Bearer <cognito-jwt>`.
- **OAuth**: "Sign in with Google" via Cognito identity-provider federation (free Google
  OAuth client registered once). Email/password, logout, refresh, verification, and
  password reset all come from the user pool; transactional emails via SES.
- **Backend (FastAPI middleware)**: verify JWTs **locally** via Cognito's JWKS (cached);
  attach `{user_id, email}`. Same middleware shape as any OIDC issuer — only the issuer
  URL is config, so swapping issuers later (Keycloak at white-label stage for institute
  SSO) touches one env var and nothing else.
- App tables store the Cognito `sub` as user id; we never handle passwords.

## Responsive strategy

- **Desktop (≥1024px)**: sidebar + chat + evidence panel (panel collapsible).
- **Tablet**: sidebar collapses to icons (Mike's SidebarContext pattern); evidence panel
  overlays as a sheet instead of splitting.
- **Mobile**: single column. Evidence panel becomes a **bottom sheet** opened by citation
  tap — PDF page renders scaled-to-width with the highlight centered. Tool timeline
  collapses by default to one status line. Chat input fixed bottom with safe-area inset.
- Tailwind breakpoints only — no separate mobile components; block renderer is already
  linear/stackable by design.

## Build order

| Phase | Frontend deliverables |
|---|---|
| 0 | Shell, auth, space list/home, upload + ingest status, visualizer v1 (no highlights) |
| 1 | Chat view: full block renderer, SSE reducer, citation chips → visualizer highlight, clarification card |
| 2 | Feedback bar, confidence chip, abstention/uncited styling |
| 3 | Question bank table + filters, approval card with question preview |
| 4 | Workflows page, space members/sharing UI, artifacts list + download |
