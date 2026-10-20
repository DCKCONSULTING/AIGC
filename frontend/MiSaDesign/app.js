const routes = {
  landing: ["Public", "Welcome"], login: ["Account", "Sign in"], onboarding: ["Getting started", "Set up your workspace"],
  pricing: ["Public", "Plans"], home: ["Workspace", "Today"], create: ["Create", "New video"],
  showcase: ["Create", "AI video lab"],
  products: ["Library", "Products"], product: ["Products", "Storii food container"], reference: ["Create", "Reference analysis"],
  brief: ["Create", "Creative brief"], storyboard: ["Create", "Storyboard"], generating: ["Create", "Production in progress"],
  editor: ["Create", "Review video"], publish: ["Create", "Publish"], calendar: ["Content", "Calendar"],
  analytics: ["Content", "Performance"], brand: ["Workspace", "Brand voice"], assets: ["Library", "Assets & presenters"],
  billing: ["Workspace", "Plan & usage"], team: ["Workspace", "Team"], integrations: ["Workspace", "Connected accounts"],
  settings: ["Workspace", "Settings & privacy"], support: ["Support", "Help centre"], adminReview: ["Operations", "Review queue"],
  reviewDetail: ["Operations", "Quality review"], operations: ["Operations", "Generation jobs"], merchants: ["Operations", "Merchants"],
  compliance: ["Operations", "Rights & consent"], designmap: ["Prototype", "All pages"]
};

const navSections = [
  ["Create", [["home","⌂","Today"],["create","＋","Create video"],["showcase","✦","AI video lab"],["products","▣","Products"],["calendar","□","Calendar"]]],
  ["Improve", [["analytics","↗","Performance"],["brand","Aa","Brand voice"],["assets","◉","Assets"]]],
  ["Manage", [["integrations","↔","Connected accounts"],["billing","RM","Plan & usage"],["designmap","◇","All designs"]]],
  ["Internal", [["adminReview","✓","Review queue","4"],["operations","≋","Generation jobs"]]]
];

const allScreens = [
  ["landing","Public landing","Explains the product promise and route to trial","Public"], ["login","Sign in","Email, passkey and account recovery","Public"],
  ["pricing","Pricing","RM plans and deliverable allowances","Public"], ["onboarding","Merchant onboarding","Business, language, shop and first product","Merchant"],
  ["home","Today","Work in progress, next actions and recent videos","Merchant"], ["create","New video","Choose product and creation method","Merchant"], ["showcase","AI video lab","Prompt, model, references and animated concept samples","Merchant"],
  ["products","Product library","Accuracy status for every product","Merchant"], ["product","Product record","Facts, variants, claims and evidence","Merchant"],
  ["reference","Reference analysis","Analyse structure with rights confirmation","Merchant"], ["brief","Creative brief","Audience, offer, language and constraints","Merchant"],
  ["storyboard","Storyboard","Approve script and scene plan before spend","Merchant"], ["generating","Production progress","Transparent asynchronous job state","Merchant"],
  ["editor","Review & correct","Video preview, proof rail and precise editing","Merchant"], ["publish","Publish","Final checks, caption, account and consent","Merchant"],
  ["calendar","Calendar","Planned, draft and published content","Merchant"], ["analytics","Performance","Accepted videos, corrections and available results","Merchant"],
  ["brand","Brand voice","Language, pronunciation and reusable tone","Merchant"], ["assets","Assets & presenters","Rights-aware reusable media library","Merchant"],
  ["billing","Plan & usage","Spend, credits, invoices and limits","Merchant"], ["team","Team","Roles, invitations and approvals","Merchant"],
  ["integrations","Connected accounts","Shop, TikTok and commerce connections","Merchant"], ["settings","Settings & privacy","Data, retention, deletion and notifications","Merchant"],
  ["support","Help centre","Guided fixes and support tickets","Merchant"], ["adminReview","Review queue","Prioritised human quality checks","Operations"],
  ["reviewDetail","Quality review","Side-by-side evidence and video checks","Operations"], ["operations","Generation jobs","Provider state, retry and cost controls","Operations"],
  ["merchants","Merchant operations","Health, usage and support context","Operations"], ["compliance","Rights & consent","Consent expiry, licences and audit trail","Operations"]
];

function pageHead(eyebrow, title, description, actions = "") {
  return `<header class="page-head"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1>${description ? `<p>${description}</p>` : ""}</div>${actions ? `<div class="page-actions">${actions}</div>` : ""}</header>`;
}
function btn(label, route, cls="primary-button") { return `<button class="${cls}" data-route="${route}">${label}</button>`; }
function action(label, message, cls="secondary-button") { return `<button class="${cls}" data-action="${message}">${label}</button>`; }
function publicHeader(route="landing") {
  const onLanding = route === "landing";
  return `<header class="public-header">
    <button class="misa-logo" data-route="landing" aria-label="MiSa home">
      <span class="misa-logo-word">MiSa</span>
      <span class="misa-logo-tag">AI video generation platform</span>
    </button>
    <nav class="public-links" aria-label="Public navigation">
      <button ${onLanding?'data-scroll="how"':'data-route="landing"'}>How it works</button>
      <button ${onLanding?'data-scroll="examples"':'data-route="landing"'}>Examples</button>
      <button data-route="pricing">Pricing</button>
    </nav>
    <div class="public-actions">
      <button class="public-signin" data-route="login">Sign in</button>
      <button class="public-create" ${onLanding?'data-scroll="free-trial"':'data-route="create"'}>${onLanding?'Try 15 sec free':'Create video'}</button>
    </div>
  </header>`;
}
function proofRail(warn=false) {
  return `<div class="proof-rail">
    <div class="proof-item"><span class="proof-dot">✓</span><span class="proof-copy"><strong>Product facts</strong><small>12 approved facts · price RM39.90</small></span><small>Passed</small></div>
    <div class="proof-item"><span class="proof-dot">✓</span><span class="proof-copy"><strong>Malaysian language</strong><small>Conversational BM · 2 brand pronunciations</small></span><small>Passed</small></div>
    <div class="proof-item"><span class="proof-dot">✓</span><span class="proof-copy"><strong>Usage rights</strong><small>Merchant product footage and licensed music</small></span><small>Passed</small></div>
    <div class="proof-item"><span class="proof-dot ${warn?'warn':''}">${warn?'!':'✓'}</span><span class="proof-copy"><strong>Visual quality</strong><small>${warn?'One scene needs human review':'Packaging and captions checked'}</small></span><small>${warn?'Review':'Passed'}</small></div>
  </div>`;
}
function productionSteps(active=1) {
  const steps = ["Brief","Concepts","Storyboard","Generate","Review","Publish"];
  return `<nav class="production-flow" aria-label="Video creation progress">${steps.map((label,index)=>{
    const step = index + 1;
    const state = step === active ? "active" : step < active ? "complete" : "";
    return `<span class="production-step ${state}" ${step === active ? 'aria-current="step"' : ""}><b>${String(step).padStart(2,"0")}</b>${label}</span>`;
  }).join("")}</nav>`;
}
function videoRows() {
  return `<div class="list">
    <div class="list-row"><div class="thumb"></div><div class="list-copy"><strong>Storii: susun peti ais</strong><small>37 sec · BM santai · updated 18 min ago</small></div><span class="status review">Review</span></div>
    <div class="list-row"><div class="thumb pink"></div><div class="list-copy"><strong>Weekend offer — cookware set</strong><small>32 sec · BM + English · yesterday</small></div><span class="status ready">Ready</span></div>
    <div class="list-row"><div class="thumb green"></div><div class="list-copy"><strong>Rak kasut ruang kecil</strong><small>41 sec · BM helpful · 2 days ago</small></div><span class="status draft">Draft</span></div>
  </div>`;
}

const views = {
  landing: () => `<div class="public-landing">
    <section class="misa-hero" aria-labelledby="hero-title">
      <div class="hero-copy-block">
        <div class="malaysia-pill"><span aria-hidden="true">🇲🇾</span> Your first 15 seconds are on us</div>
        <h1 id="hero-title">See your product<br>as a <span>15-sec video.</span> Free.</h1>
        <p>Choose any e-commerce product, tell MiSa your angle, and watch your first vertical video take shape.</p>
        <div class="hero-ctas">
          <button class="hero-create" data-scroll="free-trial">Try it now <span aria-hidden="true">↓</span></button>
          <button class="hero-watch" data-scroll="examples"><span aria-hidden="true">▶</span> Watch examples</button>
        </div>
        <div class="language-row"><span aria-hidden="true">◎</span> No card needed <i>·</i> 9:16 <i>·</i> BM + English</div>
      </div>

      <div id="free-trial" class="free-trial-card" aria-label="Create a free 15-second video mock-up">
        <div class="trial-accent" aria-hidden="true"></div>
        <div class="trial-form">
          <div class="trial-heading">
            <div><span class="trial-kicker">Free video mock-up</span><h2>Show us your product.</h2></div>
            <span class="free-badge">FREE · 15 SEC</span>
          </div>
          <div class="trial-step-label"><b>1</b><span>Choose a product</span></div>
          <div class="trial-selects">
            <label>Category<select id="trialCategory" aria-label="Product category"><option>Home & Kitchen</option><option>Beauty & Personal Care</option><option>Fashion</option><option>Food & Beverage</option><option>Electronics</option><option>Baby & Kids</option><option>Pet Supplies</option><option>Sports & Outdoors</option><option>Automotive</option><option>Other</option></select></label>
            <label>Product<select id="trialProduct" aria-label="Product"><option>Penang Air Crisp</option><option>Add my own product…</option></select></label>
          </div>
          <button class="trial-upload" data-action="Product uploader opened"><span>＋</span><span><strong>Upload your product</strong><small>Photo, product link or marketplace listing</small></span></button>
          <div class="trial-step-label"><b>2</b><span>Tell MiSa what to create</span></div>
          <label class="trial-prompt-label" for="trialPrompt">Your prompt</label>
          <div class="trial-prompt-wrap">
            <textarea id="trialPrompt">Create an energetic 15-second product video for busy Malaysian families. Show crispy fries with less oil, use a friendly local host, and end with “Makan sedap, senang je.”</textarea>
            <span id="trialPromptCount">171 / 300</span>
          </div>
          <div class="prompt-starters" aria-label="Prompt suggestions"><button data-prompt-add="Make it feel premium">Premium</button><button data-prompt-add="Use a casual Bahasa Malaysia tone">BM santai</button><button data-prompt-add="End with a clear shop-now call to action">Shop now CTA</button></div>
          <div class="trial-settings"><span>▯ 9:16 vertical</span><span>◷ 15 seconds</span><span>文 BM + English</span></div>
          <button class="trial-generate" data-free-generate><span>✦</span><strong>Generate my free video</strong><em>No credit card</em></button>
          <p class="trial-note">One free watermarked mock-up per business. Sign in to edit, export or create more.</p>
        </div>
        <aside class="trial-preview" aria-label="15-second vertical video preview">
          <div class="trial-preview-top"><span>LIVE PREVIEW</span><strong>9:16</strong></div>
          <div class="trial-video-frame">
            <div class="trial-scene-label">HOME & KITCHEN</div>
            <div class="trial-video-copy"><small>Busy day?</small><strong>Crispy dinner.<br>Kurang minyak.</strong></div>
            <div class="trial-price">15 min<br><span>to makan</span></div>
            <button class="trial-play" data-preview-play aria-label="Play video preview">▶</button>
            <div class="trial-caption">“Makan sedap, senang je.”</div>
            <div class="trial-watermark">MiSa mock-up</div>
          </div>
          <div class="trial-progress"><span class="trial-progress-label">Your 15-sec story</span><div><i></i></div><time>00:15</time></div>
          <div class="trial-scenes"><span class="active">Hook</span><span>Demo</span><span>Benefit</span><span>CTA</span></div>
        </aside>
      </div>
    </section>

    <section id="how" class="public-section how-section">
      <div class="public-kicker">From product to post</div>
      <h2>Everything your product video needs.<br><span>Nothing you have to learn.</span></h2>
      <div class="how-grid">
        <article><div class="how-icon">01</div><h3>Choose any product</h3><p>Select an e-commerce category, pick from your catalogue or upload a new product.</p></article>
        <article><div class="how-icon">02</div><h3>Say what you want</h3><p>Write naturally. Tell MiSa the audience, benefit and action—no prompt expertise needed.</p></article>
        <article><div class="how-icon">03</div><h3>Watch your mock-up</h3><p>Get one free 15-second vertical concept, then sign in only if you want to take it further.</p></article>
      </div>
    </section>

    <section id="examples" class="public-section examples-section">
      <div class="examples-head"><div><div class="public-kicker">Made with MiSa</div><h2>One product. Many stories.</h2></div><button class="text-link" data-route="showcase">Explore the video lab →</button></div>
      <div class="example-grid">
        <article class="example-card example-cyan"><div class="example-media media-air"><span>Product demo</span><button data-action="Playing product demo" aria-label="Play product demo">▶</button></div><h3>Clean product close-up</h3><p>15 sec · BM</p></article>
        <article class="example-card example-violet"><div class="example-media media-cup"><span>Lifestyle story</span><button data-action="Playing lifestyle story" aria-label="Play lifestyle story">▶</button></div><h3>Morning routine</h3><p>30 sec · English</p></article>
        <article class="example-card example-pink"><div class="example-media media-social"><span>Creator format</span><button data-action="Playing creator format" aria-label="Play creator format">▶</button></div><h3>Problem to product</h3><p>45 sec · BM + English</p></article>
      </div>
    </section>

    <section class="public-section public-price-strip">
      <div><div class="public-kicker">Start creating</div><h2>Your first product deserves a better video.</h2><p>Build the complete story in one guided workspace.</p></div>
      <div class="price-strip-actions"><button class="hero-create" data-scroll="free-trial">Try 15 sec free →</button><button class="hero-watch" data-route="pricing">View pricing</button></div>
    </section>
    <footer class="public-footer"><button class="misa-logo" data-route="landing"><span class="misa-logo-word">MiSa</span><span class="misa-logo-tag">AI video generation platform</span></button><p>Made for Malaysian brands. Designed for the way we speak.</p><button class="text-link" data-route="designmap">View all prototype screens →</button></footer>
  </div>`,

  login: () => `<section class="page"><div class="grid two" style="max-width:920px;margin:6vh auto"><div class="card hero-card"><div class="eyebrow" style="color:#ffc928">Welcome back</div><h1 style="font-size:47px">Your next video is already waiting.</h1><p>Continue drafts, approve corrections and see what is ready to publish.</p></div><div class="card" style="padding:34px">${pageHead("Account","Sign in","Use your business email.")}
    <div class="field"><label>Email</label><input value="william@example.com" /></div><div class="field"><label>Password <span>Forgot password?</span></label><input type="password" value="password" /></div>${btn("Sign in","home")}
    <p style="font-size:11px">New to MISA? <button class="quiet-button" data-route="onboarding">Set up a merchant workspace</button></p></div></div></section>`,

  pricing: () => `<section class="page">${pageHead("Plans","Pay for accepted production","Plans are shown in RM and include a defined correction allowance. Final pricing will be validated in the paid pilot.",btn("Start pilot","onboarding"))}
    <div class="grid three"><div class="card"><div class="eyebrow">Try</div><h2>One video</h2><div class="metric"><span class="value">RM —</span><span class="label">Pilot price to be tested</span></div>${btn("Create first video","create","secondary-button")}</div>
    <div class="card" style="border:2px solid var(--pandan)"><span class="chip green">Suggested pilot</span><h2 style="margin-top:12px">Merchant monthly</h2><div class="metric"><span class="value">RM —</span><span class="label">Defined completed-video allowance</span></div>${btn("Join pilot","onboarding")}</div>
    <div class="card"><div class="eyebrow">Teams</div><h2>Managed production</h2><div class="metric"><span class="value">Custom</span><span class="label">Shared products, roles and review</span></div>${action("Talk to us","Request recorded")}</div></div>
  </section>`,

  onboarding: () => `<section class="page">${pageHead("Step 2 of 4","How should MISA sound?","Choose your default. Every video can still use a different style.")}
    <div class="stepper"><span class="step-dot active"></span><span class="step-dot active"></span><span class="step-dot"></span><span class="step-dot"></span></div>
    <div class="grid split"><div class="card form-card"><div class="field"><label>Primary language</label><select><option>Bahasa Malaysia</option><option>English (Malaysia)</option><option>Mandarin (Malaysia)</option><option>Tamil (Malaysia)</option></select></div>
    <div class="field"><label>How do you usually speak to customers?</label><div class="choice-grid"><button class="choice selected" data-select><span class="choice-icon">☻</span><strong>Santai & friendly</strong><small>Natural, helpful and not pushy</small></button><button class="choice" data-select><span class="choice-icon">●</span><strong>Direct & practical</strong><small>Feature-first and concise</small></button><button class="choice" data-select><span class="choice-icon">✦</span><strong>Premium</strong><small>Calm and considered</small></button></div></div>
    <div class="field"><label>Say or type one sentence in your usual style <span>Optional</span></label><textarea>Barang ni memang senang pakai, especially kalau ruang dapur kecil.</textarea></div>${btn("Continue to shop connection","integrations")}</div>
    <aside class="card"><div class="eyebrow">What we remember</div><h2>Your approved voice</h2><p>MISA remembers wording and pronunciation you approve. You can view, export or delete these preferences.</p><div class="notice">Language preferences are chosen by you. They are not inferred from appearance or ethnicity.</div></aside></div>
  </section>`,

  home: () => `<section class="page">
    <div class="card hero-card"><div class="eyebrow" style="color:#ffc928">Friday · 29 August</div><h1>Three products could use a fresh video this week.</h1><p>Your Storii offer ends Sunday. We prepared a practical BM angle using its approved product record.</p><div class="actions">${btn("Make the Storii video","create","primary-button sun")}${btn("View content calendar","calendar","secondary-button")}</div></div>
    <div class="grid four" style="margin-top:18px"><div class="card metric"><span class="label">Ready to publish</span><span class="value">2</span><span class="delta">All checks passed</span></div><div class="card metric"><span class="label">Needs your review</span><span class="value">1</span><span class="delta">One visual check</span></div><div class="card metric"><span class="label">Accepted within 1 correction</span><span class="value">76%</span><span class="delta">Pilot workspace sample</span></div><div class="card metric"><span class="label">Usage this month</span><span class="value">8/12</span><span class="delta">4 productions remain</span></div></div>
    <div class="section-head"><h2>Recent production</h2><button class="quiet-button" data-route="calendar">View all</button></div><div class="card">${videoRows()}</div>
  </section>`,

  create: () => `<section class="page">${pageHead("MiSa Studio","Create a product video","Choose a product and tell us the result you want. MiSa will shape the story, host, voice and captions.")}
    ${productionSteps(1)}
    <div class="grid split create-studio-grid"><div class="card form-card"><div class="field"><label>Product</label><select><option>Storii food container · 1.8L</option><option>Non-stick cookware set · 5 piece</option><option>Slim shoe rack · 4 tier</option></select></div>
    <div class="field"><label>How do you want to begin?</label><div class="choice-grid"><button class="choice selected" data-select><span class="choice-icon">✎</span><strong>Tell MISA</strong><small>Type or record what the video should say</small></button><button class="choice" data-route="reference"><span class="choice-icon">↗</span><strong>Use inspiration</strong><small>Analyse an authorised reference</small></button><button class="choice" data-select><span class="choice-icon">▣</span><strong>Use a proven format</strong><small>Question, demonstration or offer</small></button></div></div>
    <div class="field"><label>Instruction</label><textarea>Buat video 35 saat. BM santai. Tunjuk senang susun dalam peti ais dan promo RM39.90 sampai Ahad. Jangan cakap leak-proof.</textarea></div>
    <div class="notice">MiSa found an approved product demonstration and 12 verified facts. The RM39.90 offer still needs an expiry date.</div><div style="margin-top:20px">${btn("Prepare creative brief","brief")}</div></div>
    <aside class="card creation-preview"><div class="eyebrow">Your video</div><div class="phone-preview"><div class="phone-screen"><div class="product-shape"></div><div class="caption">Senang nampak, senang susun.</div><div class="controls"><span>00:00 / 00:35</span><span>▶</span></div></div></div><div class="preview-specs"><span>9:16 vertical</span><span>BM + English</span><span>35 sec</span></div><p>Product-first video for Malaysian social commerce.</p></aside></div>
  </section>`,

  showcase: () => `<section class="page">${pageHead("AI video lab","Turn one idea into campaign-ready motion.","Explore styles, direct the model and start from product evidence or an authorised reference.",btn("Start from a product","create"))}
    <div class="generator-stage card">
      <div class="tabs"><button class="tab active">Text to video</button><button class="tab">Image to video</button><button class="tab">Reference to video</button></div>
      <div class="generator-input"><textarea aria-label="Video prompt">Cinematic vertical product video for a transparent food container in a modern Malaysian kitchen. Energetic opening, accurate product proportions, conversational BM captions, clean price reveal.</textarea><button class="add-media" data-action="Media picker opened">＋ Add product media</button></div>
      <div class="generator-toolbar"><div class="generator-options"><button class="model-pill" data-action="Model selector opened"><span class="model-spark">✦</span><span><small>Production mode</small><strong>Product fidelity</strong></span><b>⌄</b></button><button class="model-pill" data-action="Ratio selector opened"><span>▯</span><span><small>Ratio</small><strong>9:16</strong></span></button><button class="model-pill" data-action="Duration selector opened"><span>◷</span><span><small>Duration</small><strong>10 sec</strong></span></button><button class="model-pill" data-action="Language selector opened"><span>Aa</span><span><small>Language</small><strong>BM · Local</strong></span></button></div>${btn("Generate concepts","generating","primary-button generate-button")}</div>
    </div>
    <div class="section-head"><div><div class="eyebrow">Style visualisations</div><h2>See the creative direction in motion</h2></div><span class="chip">Concept loops · not model output</span></div>
    <div class="video-gallery">
      <article class="video-concept"><div class="motion-preview fridge"><span class="motion-light"></span><span class="motion-object box-one"></span><span class="motion-object box-two"></span><span class="motion-copy"><small>SPACE-SAVING</small><strong>Susun cantik.<br>Nampak semua.</strong></span><span class="motion-timeline"><i></i></span><button class="motion-play" data-action="Concept preview toggled">▶</button></div><div class="concept-meta"><div><span class="chip green">Product demo</span><h3>Fresh-space reveal</h3><p>Fast hook · macro details · clean offer card</p></div>${action("Use this style","Style added to new brief","secondary-button")}</div></article>
      <article class="video-concept"><div class="motion-preview beauty"><span class="motion-light"></span><span class="motion-object bottle"></span><span class="motion-ring ring-a"></span><span class="motion-ring ring-b"></span><span class="motion-copy"><small>PREMIUM GLOW</small><strong>Details that<br>feel expensive.</strong></span><span class="motion-timeline"><i></i></span><button class="motion-play" data-action="Concept preview toggled">▶</button></div><div class="concept-meta"><div><span class="chip red">Cinematic</span><h3>Luxury product orbit</h3><p>Slow camera · luminous surface · premium pacing</p></div>${action("Use this style","Style added to new brief","secondary-button")}</div></article>
      <article class="video-concept"><div class="motion-preview social"><span class="motion-light"></span><span class="motion-object phone-product"></span><span class="social-pop pop-one">✓ Senang guna</span><span class="social-pop pop-two">RM39.90</span><span class="motion-copy"><small>SCROLL STOPPER</small><strong>Terus nampak<br>kelebihan.</strong></span><span class="motion-timeline"><i></i></span><button class="motion-play" data-action="Concept preview toggled">▶</button></div><div class="concept-meta"><div><span class="chip yellow">TikTok native</span><h3>Seller-style proof</h3><p>Question hook · fast benefits · direct CTA</p></div>${action("Use this style","Style added to new brief","secondary-button")}</div></article>
    </div>
    <div class="section-head"><h2>Recent generations</h2><button class="quiet-button" data-route="calendar">View all</button></div><div class="card">${videoRows()}</div>
  </section>`,

  products: () => `<section class="page">${pageHead("Accuracy starts here","Products","Approved facts and real product evidence are reused across future videos.",btn("Add product","product"))}
    <div class="grid four"><div class="card metric"><span class="label">Approved products</span><span class="value">18</span><span class="delta">Ready for creation</span></div><div class="card metric"><span class="label">Needs information</span><span class="value">3</span><span class="delta">Price or demonstration</span></div><div class="card metric"><span class="label">Offers expiring</span><span class="value">2</span><span class="delta">Within 3 days</span></div><div class="card metric"><span class="label">Product errors released</span><span class="value">0</span><span class="delta">Pilot workspace</span></div></div>
    <div class="section-head"><h2>Product library</h2><div><input aria-label="Search products" placeholder="Search products" style="padding:10px;border:1px solid var(--line);border-radius:10px"></div></div>
    <div class="grid three"><div class="card clickable" data-route="product"><div class="thumb" style="width:100%;height:145px"></div><h2 style="margin-top:14px">Storii food container</h2><p>1 variant · 12 approved facts</p><span class="status ready">Ready</span></div><div class="card clickable" data-route="product"><div class="thumb pink" style="width:100%;height:145px"></div><h2 style="margin-top:14px">Non-stick cookware</h2><p>3 variants · missing coating evidence</p><span class="status review">Check facts</span></div><div class="card clickable" data-route="product"><div class="thumb green" style="width:100%;height:145px"></div><h2 style="margin-top:14px">Slim shoe rack</h2><p>2 variants · real demonstration available</p><span class="status ready">Ready</span></div></div>
  </section>`,

  product: () => `<section class="page">${pageHead("Product record","Storii food container","Everything MISA is allowed to say or show about this product.",`${btn("Make video","create")}${action("Save changes","Product record saved")}`)}
    <div class="grid split"><div class="grid"><div class="card"><div class="tabs"><button class="tab active">Facts</button><button class="tab">Assets</button><button class="tab">Variants</button><button class="tab">Corrections</button></div>
      <div class="grid two"><div class="field"><label>Approved name</label><input value="Storii food container" /></div><div class="field"><label>Variant</label><input value="Clear · 1.8L" /></div><div class="field"><label>Approved price</label><input value="RM39.90" /></div><div class="field"><label>Offer expiry</label><input value="31 August 2026" /></div></div>
      <div class="field"><label>Approved claims</label><textarea>Stackable. Transparent body. Suitable for organising dry or refrigerated food. Hand wash recommended.</textarea></div>
      <div class="field"><label>Do not claim</label><textarea>Leak-proof. Microwave-safe. Dishwasher-safe.</textarea></div></div>
      <div class="card"><h2>Evidence</h2><p>Original product photographs and demonstration footage.</p><div class="grid three"><div class="dropzone"><strong>Front & label</strong><span class="status ready">Approved</span></div><div class="dropzone"><strong>Real use</strong><span class="status ready">Approved</span></div><div class="dropzone"><strong>Scale reference</strong><span class="status ready">Approved</span></div></div></div></div>
    <aside class="card"><div class="eyebrow">Product proof</div><h2>Ready for production</h2>${proofRail()}</aside></div>
  </section>`,

  reference: () => `<section class="page">${pageHead("Inspiration","Use a reference responsibly","MISA extracts the hook, pacing and story pattern. It creates new material for your product.")}
    <div class="grid split"><div class="card form-card"><div class="field"><label>Reference link or authorised file</label><input value="https://www.tiktok.com/@creator/video/…" /></div><div class="notice">A public link does not prove reuse rights. MISA will analyse supported metadata or an authorised upload; it will not copy a creator’s face, voice or footage without permission.</div>
      <div class="field" style="margin-top:18px"><label>What do you like about it?</label><textarea>The first 3-second problem hook, fast demonstration and simple price reveal.</textarea></div>
      <label style="display:flex;gap:9px;font-size:12px"><input type="checkbox" checked> I own this material or have permission to use it as a reference.</label><div style="margin-top:20px">${btn("Analyse structure","brief")}</div></div>
      <aside class="card"><div class="eyebrow">Analysis preview</div><h2>Original structure, new execution</h2><p><span class="chip yellow">0–3 sec</span> Problem hook</p><p><span class="chip">3–14 sec</span> Three quick proofs</p><p><span class="chip green">14–23 sec</span> Offer and CTA</p></aside></div>
  </section>`,

  brief: () => `<section class="page">${pageHead("Before production","Confirm the creative brief","MISA prepared this from your instruction and approved product record.")}${productionSteps(2)}
    <div class="grid split"><div class="card form-card"><div class="grid two"><div class="field"><label>Audience</label><input value="Malaysians organising a small kitchen" /></div><div class="field"><label>Target duration</label><select><option>35 seconds</option><option>20 seconds</option><option>45 seconds</option></select></div><div class="field"><label>Language</label><select><option>Conversational BM</option></select></div><div class="field"><label>Call to action</label><input value="Tengok pilihan sekarang" /></div></div>
      <div class="field"><label>Main message</label><textarea>Senang nampak isi, senang susun, sesuai untuk ruang peti ais yang kecil.</textarea></div><div class="field"><label>Offer</label><input value="RM39.90 until 31 August 2026" /></div><div class="field"><label>Creative constraints</label><textarea>Use real product footage for demonstrations. No leak-proof claim. No fake testimonial.</textarea></div>${btn("Prepare storyboard","storyboard")}</div>
      <aside class="card"><div class="eyebrow">Estimated production</div><h2>4 scenes · 35–38 sec</h2><p>2 real product scenes, 1 generated environment scene and 1 offer card.</p><div class="notice">Final cost is reserved only after you approve the storyboard.</div></aside></div>
  </section>`,

  storyboard: () => `<section class="page">${pageHead("Approve before generation","Your storyboard","Review facts, narration and production method before paid generation begins.",`${btn("Approve & produce","generating")}${action("Save draft","Storyboard saved")}`)}${productionSteps(3)}
    <div class="grid split"><div class="card"><div class="timeline">
      <div class="scene"><span class="scene-time">00–04s</span><span class="scene-img"></span><span class="scene-copy"><strong>Small fridge problem</strong><small>“Peti ais kecil selalu nampak semak?” · generated environment</small></span><span class="status ready">Approved</span></div>
      <div class="scene"><span class="scene-time">04–16s</span><span class="scene-img"></span><span class="scene-copy"><strong>Real product demonstration</strong><small>Stack the approved clear 1.8L containers · merchant footage</small></span><span class="status ready">Approved</span></div>
      <div class="scene"><span class="scene-time">16–28s</span><span class="scene-img"></span><span class="scene-copy"><strong>Find ingredients quickly</strong><small>Show the transparent body · approved product footage</small></span><span class="status ready">Approved</span></div>
      <div class="scene"><span class="scene-time">28–36s</span><span class="scene-img"></span><span class="scene-copy"><strong>Offer and CTA</strong><small>RM39.90 until Sunday · designed graphic</small></span><span class="status ready">Approved</span></div></div></div>
    <aside class="card"><div class="eyebrow">Preflight</div><h2>Ready to produce</h2>${proofRail()}</aside></div>
  </section>`,

  generating: () => `<section class="page">${productionSteps(4)}<div class="loading-stage"><div class="loading-orbit"></div><div class="eyebrow">Production 62%</div><h1>Building your real product demonstration</h1><p>You can leave this page. MISA will keep the job running and notify you when the quality check is ready.</p><div class="card" style="text-align:left;margin-top:28px"><div class="proof-rail"><div class="proof-item"><span class="proof-dot">✓</span><span class="proof-copy"><strong>Script and voice</strong><small>Completed</small></span><small>00:21</small></div><div class="proof-item"><span class="proof-dot">✓</span><span class="proof-copy"><strong>Scenes</strong><small>3 of 4 completed</small></span><small>02:48</small></div><div class="proof-item"><span class="proof-dot warn">…</span><span class="proof-copy"><strong>Assembly and quality check</strong><small>Waiting for final scene</small></span><small>Next</small></div></div></div><div style="margin-top:20px">${btn("Open completed preview","editor")}</div></div></section>`,

  editor: () => `<section class="page">${pageHead("Production #M-1048","Review the finished video","Make a precise change in plain language or approve it for publishing.",`${btn("Approve video","publish")}${action("Save draft","Draft saved")}`)}${productionSteps(5)}
    <div class="grid split"><div class="card"><div class="grid two"><div class="phone-preview"><div class="phone-screen"><div class="product-shape"></div><div class="caption">Senang nampak, senang susun.</div><div class="controls"><span>00:18 / 00:36</span><span>◀ ❚❚ ▶</span></div></div></div>
      <div><div class="eyebrow">Ask for a correction</div><div class="field"><textarea>Change “tengok pilihan sekarang” to “pilih warna kegemaran sekarang”. Keep everything else.</textarea></div>${action("Apply this correction","Only the affected narration, caption and timing will be updated","primary-button")}
      <div class="section-head"><h2>Scenes</h2></div><div class="timeline"><div class="scene"><span class="scene-time">01</span><span class="scene-img"></span><span class="scene-copy"><strong>Problem hook</strong><small>4 seconds</small></span></div><div class="scene"><span class="scene-time">02</span><span class="scene-img"></span><span class="scene-copy"><strong>Real demonstration</strong><small>12 seconds</small></span></div><div class="scene"><span class="scene-time">03</span><span class="scene-img"></span><span class="scene-copy"><strong>Offer</strong><small>8 seconds</small></span></div></div></div></div></div>
      <aside class="card"><div class="eyebrow">Proof rail</div><h2>3 passed · 1 review</h2>${proofRail(true)}<div class="notice" style="margin-top:15px">The final container appears slightly darker under generated lighting. Compare it with the approved photograph.</div></aside></div>
  </section>`,

  publish: () => `<section class="page">${pageHead("Final approval","Where should this video go?","You remain in control of the account, caption, disclosures and final publish action.")}${productionSteps(6)}
    <div class="grid split"><div class="card form-card"><div class="field"><label>Destination</label><select><option>TikTok · @williamretail</option><option>Download only</option></select></div><div class="field"><label>Caption</label><textarea>Peti ais kecil pun boleh nampak kemas ✨ Bekas Storii 1.8L sekarang RM39.90 sehingga Ahad. #DapurKemas #TikTokShopMY</textarea></div><div class="field"><label>Product link</label><select><option>Storii food container · Clear 1.8L</option></select></div><div class="field"><label>Schedule</label><select><option>Publish now</option><option>Saturday · 11:30 AM</option><option>Choose date and time</option></select></div>
      <label style="display:flex;gap:9px;font-size:12px;margin:15px 0"><input type="checkbox" checked> Disclose commercial content and confirm applicable music usage.</label><div class="notice">A final confirmation is required before MISA sends content to the connected account.</div><div style="margin-top:20px">${action("Confirm & publish","Publish confirmation recorded","primary-button")}${btn(" Download MP4","home","secondary-button")}</div></div>
      <aside class="card"><div class="eyebrow">Publish readiness</div><h2>All checks passed</h2>${proofRail()}<p style="font-size:11px">Publishing access depends on the connected platform’s approval and current permissions.</p></aside></div>
  </section>`,

  calendar: () => `<section class="page">${pageHead("Plan and reuse","Content calendar","See drafts, approvals, scheduled posts and published videos together.",btn("Plan video","create"))}<div class="card table-wrap"><div class="section-head" style="margin-top:0"><h2>August 2026</h2><div>${action("‹","Previous month")}${action("Today","Calendar reset")}${action("›","Next month")}</div></div><div class="calendar">${[24,25,26,27,28,29,30,31,1,2,3,4,5,6].map((d,i)=>`<div class="day"><strong>${d}</strong>${i===3?'<div class="calendar-event">Cookware offer<br>Published</div>':''}${i===5?'<div class="calendar-event yellow">Storii<br>Review needed</div>':''}${i===8?'<div class="calendar-event">Shoe rack<br>Scheduled 11:30</div>':''}</div>`).join("")}</div></div></section>`,

  analytics: () => `<section class="page">${pageHead("Merchant outcomes","Performance","Separate production quality from platform performance. Results shown here are prototype data.")}
    <div class="grid four"><div class="card metric"><span class="label">Videos accepted</span><span class="value">18</span><span class="delta">14 within one correction</span></div><div class="card metric"><span class="label">Median active time</span><span class="value">8m</span><span class="delta">Pilot sample</span></div><div class="card metric"><span class="label">Published views</span><span class="value">42.8k</span><span class="delta">Available connected data</span></div><div class="card metric"><span class="label">Attributed shop sales</span><span class="value">—</span><span class="delta">Connection unavailable</span></div></div>
    <div class="grid split" style="margin-top:18px"><div class="card"><h2>Accepted videos by week</h2><div class="bar-chart">${[45,72,58,84,69,92,78,100].map((h,i)=>`<div class="bar ${i>5?'good':''}" style="height:${h}%"><span>W${i+1}</span></div>`).join("")}</div></div><aside class="card"><div class="eyebrow">Next test</div><h2>Try a question-led hook</h2><p>Your practical demonstrations are usually watched longer than offer-first videos in the available sample.</p>${btn("Create this variation","create","secondary-button")}</aside></div>
  </section>`,

  brand: () => `<section class="page">${pageHead("Reusable language","Brand voice","The words, pronunciations and constraints MISA should remember for your workspace.",action("Save voice","Brand voice saved","primary-button"))}
    <div class="grid split"><div class="card form-card"><div class="field"><label>Default tone</label><select><option>Santai, helpful and practical</option></select></div><div class="field"><label>Example we should sound like</label><textarea>Kalau dapur kecil, benda simple macam ni memang membantu. Senang nampak barang, senang juga nak susun.</textarea></div><div class="field"><label>Words to avoid</label><input value="gempak, confirm viral, paling murah Malaysia" /></div><div class="field"><label>Code-switching</label><select><option>Natural and occasional</option><option>BM only</option><option>BM + frequent English</option></select></div></div>
      <aside class="card"><div class="eyebrow">Pronunciation book</div><h2>Approved words</h2><div class="list"><div class="list-row"><span class="proof-dot">▶</span><div class="list-copy"><strong>Storii</strong><small>STOR-ree · approved by William</small></div><span class="status ready">Saved</span></div><div class="list-row"><span class="proof-dot">▶</span><div class="list-copy"><strong>MISA</strong><small>MEE-sah · workspace default</small></div><span class="status ready">Saved</span></div></div>${action("Add pronunciation","Recorder opened")}</aside></div>
  </section>`,

  assets: () => `<section class="page">${pageHead("Reusable, rights-aware media","Assets & presenters","Only use media with known permissions for the intended output.",action("Upload asset","Upload opened","primary-button"))}
    <div class="tabs"><button class="tab active">Product footage</button><button class="tab">Presenters</button><button class="tab">Voices</button><button class="tab">Music</button><button class="tab">Brand files</button></div>
    <div class="grid four">${[["Fridge stack demo","Merchant owned","ready"],["Storii front rotation","Merchant owned","ready"],["Aina · home presenter","Licensed to 2027","ready"],["Dapur pagi music","Social organic only","review"]].map((x,i)=>`<div class="card"><div class="thumb ${i===1?'pink':i===2?'green':''}" style="width:100%;height:160px"></div><h3 style="margin-top:13px">${x[0]}</h3><p>${x[1]}</p><span class="status ${x[2]}">${x[2]==='ready'?'Available':'Check use'}</span></div>`).join("")}</div>
  </section>`,

  billing: () => `<section class="page">${pageHead("Predictable production","Plan & usage","Monitor completed videos, reserved generation and actual provider cost.",action("Manage plan","Plan manager opened","secondary-button"))}
    <div class="grid four"><div class="card metric"><span class="label">Current plan</span><span class="value">Pilot</span><span class="delta">Renews 1 Sep</span></div><div class="card metric"><span class="label">Accepted videos</span><span class="value">8/12</span><span class="delta">4 remain</span></div><div class="card metric"><span class="label">Reserved</span><span class="value">1</span><span class="delta">In production</span></div><div class="card metric"><span class="label">Spend limit</span><span class="value">RM250</span><span class="delta">Workspace protection</span></div></div>
    <div class="card" style="margin-top:18px"><h2>Usage ledger</h2><div class="table-wrap"><table><thead><tr><th>Date</th><th>Production</th><th>Result</th><th>Allowance</th><th>Charge</th></tr></thead><tbody><tr><td>29 Aug</td><td>M-1048 Storii</td><td><span class="status review">In review</span></td><td>Reserved</td><td>—</td></tr><tr><td>28 Aug</td><td>M-1042 Cookware</td><td><span class="status ready">Accepted</span></td><td>1 video</td><td>Included</td></tr><tr><td>26 Aug</td><td>M-1033 Rack</td><td><span class="status failed">Provider failed</span></td><td>Returned</td><td>RM0</td></tr></tbody></table></div></div>
  </section>`,

  team: () => `<section class="page">${pageHead("Shared approval","Team","Control who can create, approve, publish and manage billing.",action("Invite member","Invitation form opened","primary-button"))}<div class="card table-wrap"><table><thead><tr><th>Member</th><th>Role</th><th>Can publish</th><th>Status</th></tr></thead><tbody><tr><td><strong>William</strong><br><small>william@example.com</small></td><td>Owner</td><td>Yes</td><td><span class="status ready">Active</span></td></tr><tr><td><strong>Aina Rahman</strong><br><small>aina@example.com</small></td><td>Reviewer</td><td>No</td><td><span class="status ready">Active</span></td></tr><tr><td><strong>Marketing staff</strong><br><small>marketing@example.com</small></td><td>Creator</td><td>No</td><td><span class="status review">Invited</span></td></tr></tbody></table></div></section>`,

  integrations: () => `<section class="page">${pageHead("Merchant connections","Connected accounts","Connect only what is needed. Permissions can be revoked at any time.")}
    <div class="grid three"><div class="card"><span class="chip">TikTok</span><h2 style="margin-top:13px">@williamretail</h2><p>Profile and draft upload connected. Public direct publishing review pending.</p><span class="status review">Limited access</span><div style="margin-top:16px">${action("Manage permissions","Permissions opened")}</div></div>
    <div class="card"><span class="chip yellow">TikTok Shop</span><h2 style="margin-top:13px">William Home Store</h2><p>Prototype product catalogue. Production app requires appropriate partner approval and scopes.</p><span class="status draft">Sandbox</span><div style="margin-top:16px">${action("Open setup","Shop setup opened")}</div></div>
    <div class="card"><span class="chip green">Export</span><h2 style="margin-top:13px">Manual download</h2><p>Always available when a platform integration is unavailable or awaiting approval.</p><span class="status ready">Available</span></div></div>
  </section>`,

  settings: () => `<section class="page">${pageHead("Workspace controls","Settings & privacy","Manage business details, notifications, data use and account deletion.",action("Save settings","Settings saved","primary-button"))}
    <div class="grid split"><div class="card form-card"><div class="tabs"><button class="tab active">Business</button><button class="tab">Notifications</button><button class="tab">Privacy</button><button class="tab">Security</button></div><div class="field"><label>Business display name</label><input value="William Retail" /></div><div class="field"><label>Default timezone</label><select><option>Asia/Kuala Lumpur</option></select></div><div class="field"><label>Default content language</label><select><option>Bahasa Malaysia</option></select></div><label style="display:flex;gap:9px;font-size:12px"><input type="checkbox" checked> Notify me when a video is ready for review.</label></div>
    <aside class="card"><div class="eyebrow">Your data</div><h2>Export or delete</h2><p>Download product records, approved preferences and project history.</p>${action("Request data export","Export request started")}<div style="margin-top:10px">${action("Delete workspace","Deletion requires owner confirmation","danger-button")}</div></aside></div>
  </section>`,

  support: () => `<section class="page">${pageHead("Help centre","What do you need help with?","Start with the production or product involved so support can see the relevant history.")}
    <div class="grid split"><div><div class="card"><div class="field"><label>Search help</label><input placeholder="Example: my price was wrong" /></div><div class="grid two"><button class="choice" data-action="Guide opened"><span class="choice-icon">◫</span><strong>Fix a video</strong><small>Captions, pronunciation, product or scenes</small></button><button class="choice" data-action="Guide opened"><span class="choice-icon">↔</span><strong>Connect account</strong><small>TikTok, shop or publishing</small></button><button class="choice" data-action="Guide opened"><span class="choice-icon">RM</span><strong>Billing</strong><small>Usage, failures and refunds</small></button><button class="choice" data-action="Guide opened"><span class="choice-icon">⌁</span><strong>Rights & privacy</strong><small>Assets, consent, export and deletion</small></button></div></div></div>
    <aside class="card"><div class="eyebrow">Current production</div><h2>M-1048 · Storii</h2><p>Attach this production and its technical history to a support request.</p>${action("Contact support","Support form opened","primary-button")}</aside></div>
  </section>`,

  adminReview: () => `<section class="page">${pageHead("Internal workspace","Review queue","Prioritised by publication time, risk and merchant wait—not by job value.")}
    <div class="grid four"><div class="card metric"><span class="label">Waiting</span><span class="value">4</span><span class="delta">Oldest 13 min</span></div><div class="card metric"><span class="label">Product accuracy</span><span class="value">2</span><span class="delta">Requires visual check</span></div><div class="card metric"><span class="label">Language</span><span class="value">1</span><span class="delta">Pronunciation</span></div><div class="card metric"><span class="label">SLA risk</span><span class="value">0</span><span class="delta">Within target</span></div></div>
    <div class="card table-wrap" style="margin-top:18px"><table><thead><tr><th>Priority</th><th>Merchant / product</th><th>Reason</th><th>Due</th><th></th></tr></thead><tbody><tr><td><span class="status review">High</span></td><td>William Retail<br><small>Storii 1.8L</small></td><td>Generated lighting changed colour</td><td>18 min</td><td>${btn("Review","reviewDetail","secondary-button")}</td></tr><tr><td><span class="status draft">Normal</span></td><td>Kedai Dapur Mei<br><small>Pan set</small></td><td>Brand pronunciation</td><td>31 min</td><td>${btn("Review","reviewDetail","secondary-button")}</td></tr><tr><td><span class="status draft">Normal</span></td><td>Rumah Ringkas<br><small>Shoe rack</small></td><td>Unsupported durability phrase</td><td>38 min</td><td>${btn("Review","reviewDetail","secondary-button")}</td></tr></tbody></table></div>
  </section>`,

  reviewDetail: () => `<section class="page">${pageHead("Quality review #R-208","Check product appearance","The system detected a possible colour difference in scene 3.",`${action("Approve as accurate","Review approved","primary-button")}${action("Send for repair","Scene queued for targeted repair","danger-button")}`)}
    <div class="grid split"><div class="card"><div class="grid two"><div><div class="eyebrow">Approved product</div><div class="thumb" style="width:100%;height:320px"></div></div><div><div class="eyebrow">Generated scene</div><div class="thumb pink" style="width:100%;height:320px"></div></div></div><div class="field" style="margin-top:20px"><label>Reviewer note</label><textarea>The container body appears warmer in the generated scene. Replace the scene with approved real footage or correct the environment lighting.</textarea></div></div>
    <aside class="card"><div class="eyebrow">Evidence</div><h2>Storii · Clear 1.8L</h2><p>Approved front photograph captured 21 August. Merchant confirms colourless transparent body.</p>${proofRail(true)}</aside></div>
  </section>`,

  operations: () => `<section class="page">${pageHead("Internal workspace","Generation jobs","Inspect workflow state, provider cost and controlled retry history.")}
    <div class="card table-wrap"><table><thead><tr><th>Job</th><th>Stage</th><th>Provider</th><th>Attempts</th><th>Elapsed</th><th>Cost state</th></tr></thead><tbody><tr><td>M-1048-S4</td><td><span class="status review">Review</span></td><td>Video provider A</td><td>2</td><td>03:18</td><td>Within cap</td></tr><tr><td>M-1047-S2</td><td><span class="status ready">Complete</span></td><td>Video provider A</td><td>1</td><td>01:44</td><td>Reconciled</td></tr><tr><td>M-1046-S1</td><td><span class="status failed">Failed</span></td><td>Voice provider B</td><td>3 / 3</td><td>04:02</td><td>Allowance returned</td></tr></tbody></table></div>
    <div class="grid three" style="margin-top:18px"><div class="card"><h3>Queue delay</h3><p>18 seconds</p><div class="progress"><span style="width:18%"></span></div></div><div class="card"><h3>Provider success</h3><p>94.2% · prototype data</p><div class="progress"><span style="width:94%"></span></div></div><div class="card"><h3>Daily cost guard</h3><p>31% used</p><div class="progress"><span style="width:31%"></span></div></div></div>
  </section>`,

  merchants: () => `<section class="page">${pageHead("Internal workspace","Merchants","Support context, plan status and operational health.")}<div class="card table-wrap"><table><thead><tr><th>Merchant</th><th>Products ready</th><th>Accepted videos</th><th>Last active</th><th>Health</th></tr></thead><tbody><tr><td>William Retail</td><td>18</td><td>8</td><td>Today</td><td><span class="status ready">Healthy</span></td></tr><tr><td>Kedai Dapur Mei</td><td>7</td><td>3</td><td>Today</td><td><span class="status review">Needs onboarding</span></td></tr><tr><td>Rumah Ringkas</td><td>12</td><td>6</td><td>Yesterday</td><td><span class="status ready">Healthy</span></td></tr></tbody></table></div></section>`,

  compliance: () => `<section class="page">${pageHead("Internal workspace","Rights & consent","Track what can be used, where, by whom and until when.",action("Record new consent","Consent form opened","primary-button"))}
    <div class="grid four"><div class="card metric"><span class="label">Active consents</span><span class="value">34</span><span class="delta">All traceable</span></div><div class="card metric"><span class="label">Expiring in 30 days</span><span class="value">3</span><span class="delta">Renewal requested</span></div><div class="card metric"><span class="label">Restricted assets</span><span class="value">5</span><span class="delta">Organic social only</span></div><div class="card metric"><span class="label">Missing evidence</span><span class="value">0</span><span class="delta">Uploads blocked</span></div></div>
    <div class="card table-wrap" style="margin-top:18px"><table><thead><tr><th>Asset / person</th><th>Permitted use</th><th>Territory</th><th>Expiry</th><th>Status</th></tr></thead><tbody><tr><td>Aina · presenter set 01</td><td>Merchant organic + paid social</td><td>Malaysia</td><td>30 Jun 2027</td><td><span class="status ready">Active</span></td></tr><tr><td>Dapur pagi · music</td><td>Organic social only</td><td>MY / SG</td><td>15 Sep 2026</td><td><span class="status review">Renew</span></td></tr><tr><td>William · custom voice</td><td>William Retail workspace</td><td>Malaysia</td><td>Until revoked</td><td><span class="status ready">Active</span></td></tr></tbody></table></div>
  </section>`,

  designmap: () => `<section class="page">${pageHead("Responsive product system","All designed pages","Every card opens the corresponding desktop/mobile-responsive screen. Public, merchant and operations experiences share one visual language.")}
    <div class="design-map">${allScreens.map((x,i)=>`<article class="card screen-card clickable" data-route="${x[0]}"><div><span class="screen-number">${String(i+1).padStart(2,"0")} · ${x[3]}</span><strong>${x[1]}</strong><p>${x[2]}</p></div><footer><span>Responsive</span><span>Open →</span></footer></article>`).join("")}</div>
  </section>`
};

function renderNav(route) {
  document.getElementById("sidebarNav").innerHTML = navSections.map(([label,items]) => `<div class="nav-label">${label}</div>${items.map(([id,ico,text,badge])=>`<button class="nav-item ${id===route?'active':''}" data-route="${id}"><span class="ico">${ico}</span><span>${text}</span>${badge?`<span class="nav-badge">${badge}</span>`:""}</button>`).join("")}`).join("");
  document.getElementById("mobileNav").innerHTML = [["home","⌂","Today"],["create","＋","Create"],["products","▣","Products"],["calendar","□","Plan"]].map(([id,ico,text])=>`<button data-route="${id}" class="${id===route?'active':''}"><span>${ico}</span>${text}</button>`).join("");
}
function render(route) {
  if (!views[route]) route = "home";
  const isPublic = ["landing","login","pricing"].includes(route);
  const [eyebrow,title] = routes[route];
  document.body.dataset.route = route;
  document.getElementById("pageEyebrow").textContent = eyebrow;
  document.getElementById("pageTitle").textContent = title;
  document.getElementById("app").classList.toggle("public-mode",isPublic);
  document.getElementById("main").classList.toggle("public-main",isPublic);
  document.getElementById("main").innerHTML = (isPublic ? publicHeader(route) : "") + views[route]();
  renderNav(route);
  document.querySelector(".sidebar").classList.remove("open");
  document.title = `${title} — MiSa`;
  window.scrollTo({top:0,behavior:"smooth"});
}
function navigate(route) {
  if (location.hash.slice(1) === route) render(route); else location.hash = route;
}
let toastTimer;
function showToast(message) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(()=>toast.classList.remove("show"),2600);
}

document.addEventListener("click", (event) => {
  const routeTarget = event.target.closest("[data-route]");
  if (routeTarget) { event.preventDefault(); navigate(routeTarget.dataset.route); return; }
  const scrollTarget = event.target.closest("[data-scroll]");
  if (scrollTarget) {
    event.preventDefault();
    document.getElementById(scrollTarget.dataset.scroll)?.scrollIntoView({behavior:"smooth",block:"start"});
    return;
  }
  const demoTool = event.target.closest("[data-demo-tool]");
  if (demoTool) {
    demoTool.closest(".studio-toolrail")?.querySelectorAll("button").forEach(x=>x.classList.remove("active"));
    demoTool.classList.add("active");
    showToast(`${demoTool.dataset.demoTool} controls selected`);
    return;
  }
  const demoScene = event.target.closest("[data-scene]");
  if (demoScene) {
    demoScene.closest(".scene-rail")?.querySelectorAll(".demo-scene").forEach(x=>x.classList.remove("active"));
    demoScene.classList.add("active");
    const time = String(Number(demoScene.dataset.scene) * 10).padStart(2,"0");
    const timeNode = document.querySelector(".preview-time");
    const progressNode = document.querySelector(".preview-scrub i");
    if (timeNode) timeNode.textContent = `00:${time} / 01:00`;
    if (progressNode) progressNode.style.width = `${Number(demoScene.dataset.scene) * 18}%`;
    return;
  }
  const previewPlay = event.target.closest("[data-preview-play]");
  if (previewPlay) {
    const playing = previewPlay.classList.toggle("playing");
    previewPlay.textContent = playing ? "Ⅱ" : "▶";
    document.querySelector(".preview-scrub")?.classList.toggle("playing",playing);
    return;
  }
  const promptStarter = event.target.closest("[data-prompt-add]");
  if (promptStarter) {
    const prompt = document.getElementById("trialPrompt");
    if (prompt) {
      const addition = promptStarter.dataset.promptAdd;
      prompt.value = `${prompt.value.trim()} ${addition}.`.slice(0,300);
      document.getElementById("trialPromptCount").textContent = `${prompt.value.length} / 300`;
      prompt.focus();
    }
    return;
  }
  const freeGenerate = event.target.closest("[data-free-generate]");
  if (freeGenerate) {
    freeGenerate.disabled = true;
    freeGenerate.classList.add("generating");
    freeGenerate.innerHTML = '<span>✦</span><strong>Building your 15-sec story…</strong><em>About 1 min</em>';
    document.querySelector(".trial-preview")?.classList.add("ready");
    showToast("MiSa is creating your free 15-second mock-up");
    setTimeout(()=>{
      freeGenerate.disabled = false;
      freeGenerate.classList.remove("generating");
      freeGenerate.innerHTML = '<span>✓</span><strong>Your mock-up is ready · Play</strong><em>Free preview</em>';
    },1100);
    return;
  }
  const demoStatus = event.target.closest("[data-demo-status]");
  if (demoStatus) { showToast(demoStatus.dataset.demoStatus); return; }
  const actionTarget = event.target.closest("[data-action]");
  if (actionTarget) { event.preventDefault(); showToast(actionTarget.dataset.action); return; }
  const choice = event.target.closest("[data-select]");
  if (choice) {
    const grid = choice.closest(".choice-grid");
    if (grid) grid.querySelectorAll(".choice").forEach(x=>x.classList.remove("selected"));
    choice.classList.add("selected");
  }
});
document.addEventListener("input",(event)=>{
  if (event.target.id === "trialPrompt") {
    const count = document.getElementById("trialPromptCount");
    if (count) count.textContent = `${event.target.value.length} / 300`;
  }
});
document.addEventListener("change",(event)=>{
  if (event.target.id === "trialCategory") {
    const label = document.querySelector(".trial-scene-label");
    if (label) label.textContent = event.target.value.toUpperCase();
  }
});
document.getElementById("menuButton").addEventListener("click",()=>document.querySelector(".sidebar").classList.toggle("open"));
window.addEventListener("hashchange",()=>render(location.hash.slice(1) || "landing"));
render(location.hash.slice(1) || "landing");
