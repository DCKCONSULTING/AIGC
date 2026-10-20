# MISA product design specification

## Product promise

MISA is a merchant video-production workspace for Malaysia. A merchant selects an approved product, gives a short text or voice instruction, reviews a structured brief, and receives a complete video with visible product, language, rights and quality checks.

## Public entrance

The public landing page uses a bright blue–cyan–violet–pink creator palette and puts the free trial directly inside the hero. Visitors can choose an e-commerce category and product, upload their own product, write a plain-language prompt and generate one watermarked 15-second 9:16 mock-up without a credit card. A paired vertical preview makes the product purpose unmistakable before scrolling. Editing, export and additional generations move into the signed-in Studio without changing visual language.

## Signature interaction: the proof rail

Every production exposes four forms of readiness:

1. Product facts
2. Malaysian language
3. Usage rights
4. Visual quality

Warnings route to a human-review page. The proof rail appears before production, during merchant review, at publishing and in the operations portal.

## Visual system — Bright Creator Studio

- Studio white `#FFFFFF`: highly legible product workspace
- Cloud `#F6F7FB`: soft background separation
- Ink `#121524`: premium high-contrast typography
- Creator cyan `#00BDDD`: verification and one side of the video frame
- Creator fuchsia `#F93876`: creation and the opposite video-frame edge
- Marquee gold `#FFCB52`: approvals and deliberate emphasis

The interface uses **Plus Jakarta Sans** for display, body and controls, with a system sans-serif fallback. Headings use 700–800 weights, body copy stays at 400–600, and no condensed display face is used. Evidence, status and timing retain a limited monospace accent.

### Inner-page colour discipline

- At least 75% of each viewport remains white or near-white.
- Cyan–blue–violet is used for headline emphasis, active navigation and structural wayfinding.
- Neon pink is reserved for captions, progress, publishing and small attention signals.
- Creation, review and publishing share one six-step progress rail: Brief, Concepts, Storyboard, Generate, Review and Publish.
- A large 9:16 preview stays visible on the creation and review surfaces so the product never reads like a generic dashboard.
- The signature **creator seam** appears as a restrained cyan-to-pink edge on navigation and video frames, connecting every workspace screen to the public MiSa experience.

The broader layout takes directional cues from the bright, spacious category language used by HeyGen and Pippit while retaining MISA's own product-accuracy workflow. The signature **premiere edge** keeps cyan and fuchsia light inside video previews and high-energy creative moments rather than covering the full application in neon.

## Page inventory

### Public and access

1. Landing
2. Sign in
3. Pricing
4. Merchant onboarding

### Core merchant production

5. Today dashboard
6. New video
7. AI video lab and motion concept showcase
8. Product library
9. Product record
10. Reference analysis
11. Creative brief
12. Storyboard
13. Production progress
14. Review and precise correction
15. Publish

### Merchant management

16. Content calendar
17. Performance
18. Brand voice
19. Assets and presenters
20. Plan and usage
21. Team
22. Connected accounts
23. Settings and privacy
24. Help centre

### Internal operations

25. Review queue
26. Quality review
27. Generation jobs
28. Merchant operations
29. Rights and consent

## Video showcase status

The AI video lab contains animated motion concepts for interaction and art-direction review. They are explicitly labelled as concept loops, not model output. Replace them with original generated MP4/WebM samples after the production workspace has approved video-model access and usage rights.

## Responsive behaviour

- Desktop uses a persistent production sidebar and a wide review workspace.
- Tablet converts multi-column cards to two or one column.
- Mobile uses a compact header, four-item bottom navigation and an off-canvas complete menu.
- Tables remain horizontally scrollable where converting them into cards would hide operational relationships.
- Keyboard focus, skip navigation and reduced-motion preferences are supported.

## Production handoff priorities

1. Replace sample records with typed domain models and persisted data.
2. Implement authentication, merchant isolation and role permissions.
3. Implement private upload storage and product-fact approval.
4. Build durable background generation jobs and provider adapters.
5. Add deterministic composition and component-level corrections.
6. Implement quality-review workflows and an audit trail.
7. Add billing and per-job cost limits.
8. Integrate publishing only after platform approval and consent controls.

## Scope boundary

The prototype deliberately represents unknown commercial prices, unapproved integrations and pilot measurements as unknown or illustrative. Production must not convert these placeholders into claims without evidence.
