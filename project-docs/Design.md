DESIGN: AI TUTOR GUIDE (FRONTEND DESIGN SYSTEM)

The look and behaviour of the React frontend in frontend/. Presentation only: no backend logic, APIs, agents, or scoring live here.
Related: [PRD](PRD.md) · [Architecture](Architecture.md) · [Rules](Rules.md) · [Tasks](Tasks.md) · [Memory](../docs/Memory.md)

---

1. DIRECTION: PLAYFUL GEOMETRIC

Stable grid, wild decoration. Content stays clean and readable. The surroundings carry playful shapes, tactile cards, chunky borders, hard shadows, and colourful accents.

Feeling: friendly, smart, playful, modern, academic, energetic. A premium AI study companion, not a corporate dashboard and not a children's app.

Priorities in order: readability, navigation, learning flow, quiz usability, clear hierarchy, accessibility, playful identity.

---

2. DESIGN TOKENS (frontend/tailwind.config.js)

COLOUR

| Token | Value | Use |
|---|---|---|
| bg | #FFFDF5 | Page background (warm cream) |
| fg / ink | #1E293B | Text and chunky borders |
| muted / muted-fg | #F1F5F9 / #64748B | Secondary surfaces and text |
| violet | #8B5CF6 | Primary actions, active navigation, AI Tutor branding, focus |
| pink | #F472B6 | Quiz highlights, needs practice, decorative accents |
| amber | #FBBF24 | Study recommendations, hover highlights |
| emerald | #34D399 | Correct answers, positive states |
| border | #E2E8F0 | Secondary borders |
| card / input | #FFFFFF | Cards and inputs |

Do not use all colours equally. The interface stays calm and colour is an accent. Difficulty colours: Simple is violet, Medium is pink, High is amber, always with the text label.

TYPOGRAPHY

| Role | Font | Weights |
|---|---|---|
| Headings, card titles, quiz questions, big numbers | Outfit | 700, 800 |
| Body, navigation, labels, chat, supporting text | Plus Jakarta Sans | 400, 500 (600 to 700 for emphasis) |

BORDERS, RADIUS, SHADOWS

| Token | Value |
|---|---|
| Chunky border | 2px solid #1E293B (secondary UI: 2px solid #E2E8F0) |
| Radius | 8px small controls, 16px cards, 24px large cards, 9999px pills and buttons |
| Shadow std | 4px 4px 0 #1E293B |
| Shadow hover | 6px 6px 0 #1E293B |
| Shadow active | 2px 2px 0 #1E293B |
| Shadow card | 8px 8px 0 #E2E8F0 |
| Focused input | 4px 4px 0 #8B5CF6 |

No blurry shadows, no glassmorphism, no heavy gradients.

MOTION

* Duration 300 ms with a bouncy easing, class .tactile.
* Buttons move up and left on hover and down and right on press.
* Cards scale and rotate slightly on hover only where appropriate (metric cards). Never rotate chat messages, text-heavy cards, forms, quiz questions, or tables.
* prefers-reduced-motion: all animation collapses, floats and spins stop, no rotation.

PATTERNS (low contrast, in index.css)

dot-grid (page background, empty states), diagonal-stripes (progress and highlight cards), grid-lines (benchmark cards).

ICONS

Lucide React, stroke width 2.5, round caps. Icons sit inside coloured circles, pills, or small containers, never floating randomly.

DECORATIVE SHAPES (DecorativeShapes.jsx)

Star, dots, and squiggle only. Circles and triangles were removed because they overlapped headings. Shapes are aria-hidden, pointer-events-none, and hidden on small screens where they would interfere.

---

3. LAYOUT AND SHELL

```text
Sidebar (288 px)   |   Top header: page title, document pill, Manage documents button
brand + 5 nav      |   Main content, max width 1200 px
```

* Sidebar: brand "AI Tutor Guide" (sparkles icon in a violet circle) and four items: Dashboard, AI Tutor, Adaptive Quiz, Evaluation. Active is violet with white text and a small hard shadow. Hover is an amber tint. Below the lg breakpoint it becomes an off-canvas menu. The sidebar has no footer text.
* Top header: page title on the left, current document as a pill and a primary Manage documents or Upload button on the right.
* Responsive: desktop is multi-column, tablet has fewer columns and decorations, mobile is one column with buttons at least 48 px tall.

---

4. COMPONENTS (frontend/src/components/)

| Component | Purpose |
|---|---|
| Shell, Sidebar, TopHeader | App frame, navigation, header |
| StickerCard | White card, 2px ink border, card shadow, optional hover rotate |
| Button (PrimaryButton, SecondaryButton, Pill) | Primary is violet with a pill shape. Secondary is outlined. Pill is for quick actions |
| Badge (StatusBadge) | Strong, Improving, Needs Practice. Icon plus text, never colour alone. Thresholds mirror the backend (70 or more strong, 60 to 69 improving, under 60 needs practice) |
| MetricCard | Icon in a coloured circle, label, large number, supporting text |
| ProgressBar | Chunky bar with role progressbar and aria values |
| SectionHeader | Optional title with a squiggle, and a subtitle. Eyebrow labels were removed |
| ChatBubble | User: violet, white text, plain text. Assistant: white with a dark border and a bot icon, renders markdown. Source pills read Source 1, Source 2 and open to show the excerpt. A failed reply gets a pink border and a Retry button. While waiting, a "Thinking..." bubble turns into a "taking longer than usual" note after 15 seconds |
| Markdown | Renders the tutor's markdown with react-markdown and remark-gfm: bold, italic, bullet and numbered lists including nested ones, headings, tables, code. Raw HTML is never rendered. Used by chat replies summary |
| EmptyState | Icon tile, title, body, optional actions, decorative shapes |
| UploadDropzone, DocumentPanel | Dashed drop area and a modal to upload, switch, and delete documents |

Inputs are white with a 2px border and 16px radius. Focus is a violet border and violet hard shadow. The chat input is large.

---

5. PAGES

| Route | Page | Content (real data only) |
|---|---|---|
| /dashboard | Dashboard | Heading "Welcome Aboard to Your Learning Forum". Metric cards (Overall Accuracy, Questions Attempted, Questions Correct, Topics Mastered). Difficulty Performance cards. Learning Progress card. Topic Performance table with status badges |
| /tutor | AI Tutor | Quick-action pills (Summarize, Key Points, Explain Simply, Glossary, Quiz Me). Chat with markdown replies. Empty state "Ready to learn?". Large input and send button. Source pills |
| /quiz | Adaptive Quiz | Phase pill, Question N of 15 with a progress bar (Simple only), question card, whole-card clickable options, Submit, feedback card (Correct or Not quite) with explanation, Phase Complete block, Reset Quiz |
| /evaluation | Evaluation | Subtitle only (no page heading). At-Risk Topics: topics below 60% with at least 2 answers, each showing accuracy, attempts, and how many points below the threshold. Below it, the System Benchmark (RAG Evaluation), locked behind a password |

THE SYSTEM BENCHMARK LOCK

* Locked state: a lock icon, the title, a password field, and an Unlock button.
* A wrong password shows "Incorrect password." under the field. If the server has no password configured, it shows that the benchmark is locked.
* After unlocking: grouped metric cards (Retrieval, Generation, System) and a per-question table. It is expanded by default and can be collapsed.
* The password is kept in memory only, so a reload locks the benchmark again.

WHY THE PAGES DO NOT REPEAT EACH OTHER

* Dashboard: raw numbers (what happened).
* Evaluation: risk analysis (what needs attention).

DELIBERATE DEVIATIONS FROM THE ORIGINAL SPEC (data honesty)

* Study Time was replaced by Questions Correct and Topics Mastered because the API has no study-time data.
* The evaluation Quiz metric group was omitted because no quiz-evaluation data exists.
* Per-difficulty question counts are not shown because /dashboard returns only accuracies.
* Source pills read Source N because chat sources carry chunk ids, not page numbers. Each pill opens the excerpt text.

---

6. EMPTY STATES

* Dashboard: "No document yet" and "Start learning to see your progress here".
* Quiz: "Upload a document to start your first quiz".
* Evaluation: "No performance data yet" and "Take an adaptive quiz to unlock performance analysis". While loading it shows "Loading performance analysis...". If no topic has 2 answers yet it says so instead of claiming nothing is at risk.
* Tutor: "Upload a document to start chatting" and "Ready to learn?".

---

7. ACCESSIBILITY CHECKLIST

* High contrast text (#1E293B on #FFFDF5) and a visible 3px violet focus outline on everything focusable.
* Semantic buttons and links, proper labels, aria-label on icon-only buttons, role progressbar with values.
* Keyboard navigable, touch targets at least 48 px on mobile, option cards are real buttons.
* Never rely on colour alone. Status badges pair an icon with text.
* Motion respects prefers-reduced-motion. Decorative elements are hidden from assistive technology.
* The benchmark password field has an aria-label and errors use role alert.

---

8. FRONTEND AND BACKEND CONTRACT

* Base URL is VITE_API_URL (default http://localhost:8000). An optional VITE_API_KEY is sent as X-API-Key.
* The session id is in localStorage["tg_session_id"]. Per-session state (documents, chat cache, current document) is in localStorage["tg_state_<session>"].
* POST /agent handles chat, quick actions (mode), and the quiz. The quiz page parses the markdown reply (lib/parseQuiz.js) for feedback and the question number. The question itself comes from quiz_details.question_dict.
* GET /dashboard feeds its page. GET /evaluation is called only after the password is entered, with an X-Benchmark-Password header.
* GET /chat/history is used to restore the conversation when a document is opened (with source excerpts). agent_trace is available but not yet used by the UI (see Tasks.md).

---

9. TECH

React 18, Vite 5, Tailwind 3, react-router-dom 6, lucide-react, react-markdown, remark-gfm. Fonts from Google Fonts (Outfit, Plus Jakarta Sans).

Files: src/pages/*, src/components/*, src/lib/{api,parseQuiz}.js, src/store.jsx, src/index.css.
