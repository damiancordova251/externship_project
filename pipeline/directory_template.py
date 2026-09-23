"""
The Campus Recruiting Directory page — markup, styles, and behavior, held as a
single template string.

It lives in its own module purely to keep build_directory.py readable; nothing
here is executed at import time. build_directory.py substitutes two
placeholders and writes the result:

    __DATA__            the whole directory payload, as inlined JSON
    __RANKING_SOURCE__  attribution text for the Top-100 inclusion set

The output is deliberately self-contained — no server, no build step, no network
fetches — so the page can be opened straight from disk and handed to a recruiter.

Security note: every candidate value is rendered through `textContent`, never
`innerHTML`, so a name or school string can never inject markup into the page.
"""

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Campus Recruiting Directory — Valon</title>
  <style>
    :root {
      --white:#FFFFFF; --n-100:#F8F6F3; --n-200:#ECE4DD; --n-300:#DCD2C6;
      --n-400:#AF9F8A; --n-500:#827057; --n-600:#5C543C; --n-700:#4A402C;
      --n-800:#31231B; --n-900:#20190F; --n-950:#231810;
      --gold-400:#EBB03C; --gold-500:#E19614; --gold-600:#BE7E10;
      --ink:#231810;
      --text-body:rgba(35,24,16,0.80); --text-secondary:rgba(35,24,16,0.60);
      --text-label:rgba(35,24,16,0.40); --border-soft:rgba(35,24,16,0.10);
      --border-hover:rgba(35,24,16,0.20); --divider:rgba(35,24,16,0.08);
      --row-hover:rgba(35,24,16,0.05);
      --radius-input:8px; --radius-card:12px;
      --shadow-menu:0 4px 12px rgba(35,24,16,0.10); --ease:150ms ease;
      --font-sans:"KMR Melange Grotesk",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
      --font-mono:"Geist Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
    }
    * { box-sizing:border-box; }
    html,body { margin:0; padding:0; background:var(--n-100); color:var(--ink);
      font-family:var(--font-sans); font-size:16px; line-height:1.4;
      -webkit-font-smoothing:antialiased; }
    :focus-visible { outline:2px solid var(--ink); outline-offset:2px; }
    :focus:not(:focus-visible) { outline:none; }
    a { color:inherit; }

    .page { max-width:960px; margin:0 auto; padding:0 24px 96px; }

    /* Header */
    .header { height:44px; padding:12px 0; display:flex; align-items:center;
      justify-content:space-between; box-sizing:content-box; }
    .header__left { display:flex; align-items:center; gap:16px; min-width:0; }
    .wordmark { display:flex; align-items:center; gap:8px; letter-spacing:-0.5px; }
    .wordmark__mark { width:28px; height:28px; display:grid; place-items:center; }
    .wordmark__mark svg { width:100%; height:100%; display:block; }
    .wordmark__name { font-size:18px; letter-spacing:-0.6px; }
    .header__divider { width:1px; height:20px; background:var(--border-soft); }
    .header__label { font-size:14px; color:var(--text-secondary); letter-spacing:-0.2px; white-space:nowrap; }
    .icon-btn { width:40px; height:40px; border-radius:50%; border:none;
      background:var(--n-100); color:var(--ink); display:grid; place-items:center;
      cursor:pointer; transition:background var(--ease); flex-shrink:0; }
    .icon-btn:hover { background:var(--n-200); }
    .icon-btn svg { width:20px; height:20px; }

    /* Intro */
    .intro { padding:48px 0 32px; }
    .intro h1 { margin:0 0 8px; font-weight:400; font-size:32px; letter-spacing:-0.8px; }
    .intro p { margin:0; font-size:16px; color:var(--text-body); max-width:64ch; }

    /* Controls */
    .controls { display:flex; flex-direction:column; gap:16px; margin-bottom:24px; }
    .search { position:relative; }
    .search__icon { position:absolute; left:16px; top:50%; transform:translateY(-50%);
      width:20px; height:20px; color:var(--text-secondary); pointer-events:none; }
    .search input { width:100%; height:48px; border-radius:var(--radius-input);
      border:1px solid var(--border-soft); background:var(--white);
      padding:12px 16px 12px 48px; font-family:var(--font-sans); font-size:16px;
      color:var(--ink); transition:border-color var(--ease); }
    .search input::placeholder { color:var(--text-secondary); }
    .search input:hover { border-color:var(--border-hover); }
    .search input:focus-visible { border-color:transparent; }
    .filters { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
    .filters__label { font-size:12px; text-transform:uppercase; letter-spacing:0.6px;
      color:var(--text-label); margin-right:8px; }
    .pill { border:1px solid var(--border-soft); border-radius:var(--radius-input);
      background:var(--white); padding:6px 12px; font-family:var(--font-sans);
      font-size:14px; color:var(--text-body); cursor:pointer;
      transition:border-color var(--ease),background var(--ease),color var(--ease);
      min-height:32px; }
    .pill:hover { border-color:var(--border-hover); }
    .pill[aria-pressed="true"] { background:var(--ink); border-color:var(--ink); color:var(--white); }

    /* Search + Filters button row */
    .search-row { display:flex; gap:8px; align-items:stretch; position:relative; }
    .search-row .search { flex:1; }
    .filters-btn { display:inline-flex; align-items:center; gap:8px; height:48px;
      padding:0 16px; border:1px solid var(--border-soft); border-radius:var(--radius-input);
      background:var(--white); color:var(--ink); font-family:var(--font-sans); font-size:15px;
      cursor:pointer; white-space:nowrap; transition:border-color var(--ease); }
    .filters-btn:hover { border-color:var(--border-hover); }
    .filters-btn svg { width:18px; height:18px; }
    .filters-btn__count { background:var(--ink); color:var(--white); font-size:12px;
      min-width:18px; height:18px; border-radius:9px; display:inline-grid; place-items:center; padding:0 5px; }

    /* Filters popup */
    .filter-popup { position:absolute; top:calc(100% + 8px); right:0; z-index:40;
      width:min(360px, 92vw); background:var(--white); border:1px solid var(--border-soft);
      border-radius:var(--radius-card); box-shadow:var(--shadow-menu); padding:20px; }
    .filter-popup[hidden] { display:none; }
    .filter-popup__section { margin-bottom:20px; }
    .filter-popup__section:last-of-type { margin-bottom:12px; }
    .filter-popup__title { font-size:12px; text-transform:uppercase; letter-spacing:0.6px;
      color:var(--text-label); margin:0 0 10px; }
    .filter-field { display:flex; align-items:center; justify-content:space-between;
      gap:12px; font-size:14px; color:var(--text-body); margin-bottom:8px; }
    .filter-input { height:36px; border:1px solid var(--border-soft); border-radius:var(--radius-input);
      background:var(--white); padding:4px 10px; font-family:var(--font-sans); font-size:14px;
      color:var(--ink); transition:border-color var(--ease); }
    .filter-input:hover { border-color:var(--border-hover); }
    .filter-input--num { width:80px; }
    .filter-daterange { display:flex; gap:12px; }
    .filter-daterange .filter-field { flex:1; flex-direction:column; align-items:flex-start; gap:4px; }
    .filter-daterange .filter-input { width:100%; }
    .filter-popup__actions { display:flex; justify-content:space-between; gap:8px; }
    .fbtn { height:40px; padding:0 16px; border-radius:var(--radius-input); border:none;
      font-family:var(--font-sans); font-size:14px; cursor:pointer; transition:background var(--ease); }
    .fbtn--secondary { background:rgba(35,24,16,0.08); color:var(--ink); }
    .fbtn--secondary:hover { background:rgba(35,24,16,0.16); }
    .fbtn--primary { background:var(--ink); color:var(--white); }
    .fbtn--primary:hover { background:rgba(35,24,16,0.9); }
    @media (max-width:480px) { .filter-popup { right:auto; left:0; } }

    .result-count { margin:0 0 16px; font-size:13px; color:var(--text-secondary); }

    /* Table */
    .table { background:var(--white); border:1px solid var(--border-soft);
      border-radius:var(--radius-card); overflow:hidden; }
    .table__head { display:grid; grid-template-columns:1fr auto 40px; align-items:center;
      gap:16px; padding:16px 24px; border-bottom:1px solid var(--divider); }
    .col-head { font-size:12px; text-transform:uppercase; letter-spacing:0.6px; color:var(--text-label); }
    .col-head--hires { text-align:right; }
    .row { display:grid; grid-template-columns:1fr auto 40px; align-items:center; gap:16px;
      width:100%; padding:16px 24px; border:none; border-bottom:1px solid var(--divider);
      background:transparent; text-align:left; font-family:var(--font-sans); cursor:pointer;
      transition:background var(--ease); }
    .row:last-child { border-bottom:none; }
    .row:hover { background:var(--row-hover); }
    .row:focus-visible { outline:2px solid var(--ink); outline-offset:-2px; }
    .row__name-wrap { display:flex; align-items:center; gap:12px; min-width:0; flex-wrap:wrap; }
    .row__name { font-size:16px; letter-spacing:-0.2px; }
    .row__hires { font-size:14px; color:var(--text-secondary); text-align:right;
      white-space:nowrap; font-variant-numeric:tabular-nums; }
    .row__chevron { color:var(--text-secondary); display:grid; place-items:center;
      transition:transform var(--ease),color var(--ease); }
    .row:hover .row__chevron { color:var(--ink); transform:translateX(2px); }
    .row__chevron svg { width:20px; height:20px; }

    /* Criteria tags */
    .tag { display:inline-flex; align-items:center; gap:6px; font-size:12px;
      letter-spacing:0.2px; padding:3px 10px 3px 8px; border-radius:999px;
      white-space:nowrap; background:var(--n-100); border:1px solid var(--border-soft);
      color:var(--text-body); }
    .tag::before { content:""; width:6px; height:6px; border-radius:50%; background:currentColor; flex-shrink:0; }
    .tag--ranked::before { background:var(--gold-500); }
    .tag--ny::before { background:var(--n-500); }
    .tag--sf::before { background:var(--ink); }
    .tag--hired::before { background:#3F7D5B; }
    .tag--fair::before { background:#2F6FB0; }
    .tag--extra::before { background:var(--n-400); }

    /* Row: stack name + next-fair line in the first column */
    .row__main { display:flex; flex-direction:column; gap:6px; min-width:0; }
    .row__sub { display:inline-flex; align-items:center; gap:6px; font-size:13px;
      color:var(--text-secondary); }
    .row__sub svg { width:14px; height:14px; flex-shrink:0; color:#2F6FB0; }
    .row__sub b { font-weight:400; color:var(--text-body); font-variant-numeric:tabular-nums; }
    .row__sub .row__sub-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }

    /* Modal: upcoming career-fair block */
    .fairs { margin:8px 0 24px; }
    .fairs__title { font-size:12px; text-transform:uppercase; letter-spacing:0.6px;
      color:var(--text-label); margin:0 0 12px; }
    .fair { display:flex; gap:14px; padding:12px 0; border-bottom:1px solid var(--divider); }
    .fair:last-child { border-bottom:none; }
    .fair__date { flex-shrink:0; width:64px; text-align:center; line-height:1.1; }
    .fair__date-m { font-size:11px; text-transform:uppercase; letter-spacing:0.6px; color:#2F6FB0; }
    .fair__date-d { font-size:22px; font-variant-numeric:tabular-nums; }
    .fair__date-y { font-size:11px; color:var(--text-label); }
    .fair__body { min-width:0; }
    .fair__name { font-size:15px; margin-bottom:2px; }
    .fair__loc { font-size:13px; color:var(--text-secondary); }
    .fair__src { font-size:13px; }
    .fair__src a { color:#2F6FB0; }
    /* Recently-passed block: muted so it reads as history, not upcoming */
    .fairs--past { opacity:0.7; }
    .fairs--past .fair__date-m { color:var(--text-label); }

    .empty { padding:64px 24px; text-align:center; color:var(--text-secondary); font-size:15px; }

    /* Modal */
    .overlay { position:fixed; inset:0; background:rgba(35,24,16,0.45); display:none;
      align-items:center; justify-content:center; padding:24px; z-index:50; }
    .overlay.open { display:flex; }
    .modal { background:var(--white); border-radius:var(--radius-card);
      box-shadow:var(--shadow-menu); width:100%; max-width:560px; max-height:82vh;
      display:flex; flex-direction:column; }
    .modal__top { display:flex; align-items:flex-start; justify-content:space-between;
      gap:16px; padding:32px 32px 16px; }
    .modal__title { margin:0 0 8px; font-weight:400; font-size:24px; letter-spacing:-0.6px; }
    .modal__meta { display:flex; align-items:center; gap:8px; flex-wrap:wrap;
      font-size:14px; color:var(--text-secondary); }
    .modal__body { overflow-y:auto; padding:8px 32px 32px; }
    .hire-group { margin-bottom:16px; }
    .hire-group__title { font-size:12px; text-transform:uppercase; letter-spacing:0.6px;
      color:var(--text-label); margin:16px 0 4px; }
    .hire { padding:16px 0; border-bottom:1px solid var(--divider); }
    .hire:last-child { border-bottom:none; }
    .hire__name { font-size:16px; margin-bottom:8px; }
    .contacts { display:flex; flex-wrap:wrap; gap:8px; }
    .contact { display:inline-flex; align-items:center; gap:6px; font-size:13px;
      padding:6px 12px; border-radius:var(--radius-input); border:1px solid var(--border-soft);
      background:var(--white); color:var(--text-body); text-decoration:none;
      transition:border-color var(--ease),background var(--ease); max-width:100%; }
    .contact:hover { border-color:var(--border-hover); background:var(--n-100); }
    .contact__label { color:var(--text-label); text-transform:uppercase; font-size:11px; letter-spacing:0.4px; }
    .contact__value { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:220px; }
    .contact--mono { font-family:var(--font-mono); }
    button.contact { cursor:pointer; }

    /* Email template picker */
    .email-menu { background:var(--white); border:1px solid var(--border-soft);
      border-radius:var(--radius-card); box-shadow:var(--shadow-menu); padding:6px;
      z-index:60; width:280px; max-width:92vw; }
    .email-menu__title { font-size:11px; text-transform:uppercase; letter-spacing:0.4px;
      color:var(--text-label); padding:6px 10px 8px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .email-menu__item { display:block; width:100%; text-align:left; border:none; background:none;
      font-family:var(--font-sans); font-size:14px; color:var(--text-body); padding:9px 10px;
      border-radius:8px; cursor:pointer; }
    .email-menu__item:hover { background:var(--row-hover); }
    .email-menu__item small { display:block; color:var(--text-label); font-size:12px; margin-top:1px; }
    .hire__none { font-size:13px; color:var(--text-secondary); font-style:italic; }
    .modal__emptystate { padding:32px 0; text-align:center; color:var(--text-secondary); font-size:14px; }

    /* Top tabs (Directory / Saved contacts) */
    .tabs { display:flex; gap:4px; margin:0 0 24px; border-bottom:1px solid var(--divider); }
    .tab { appearance:none; border:none; background:none; cursor:pointer;
      font-family:var(--font-sans); font-size:15px; color:var(--text-secondary);
      padding:10px 4px; margin-right:20px; border-bottom:2px solid transparent;
      transition:color var(--ease),border-color var(--ease); display:inline-flex; align-items:center; gap:8px; }
    .tab:hover { color:var(--ink); }
    .tab[aria-selected="true"] { color:var(--ink); border-bottom-color:var(--ink); }
    .tab__count { background:var(--n-200); color:var(--text-body); font-size:12px;
      min-width:20px; height:20px; border-radius:10px; display:inline-grid; place-items:center; padding:0 6px; }

    /* RSVP + Add-to-calendar (in the fair block) */
    .fair__rsvp { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:8px; font-size:13px; }
    .fair__rsvp-q { color:var(--text-secondary); }
    .rsvp-btn { appearance:none; font-family:var(--font-sans); font-size:13px; cursor:pointer;
      border:1px solid var(--border-soft); background:var(--white); color:var(--text-body);
      border-radius:999px; padding:4px 12px; transition:all var(--ease); }
    .rsvp-btn:hover { border-color:var(--border-hover); }
    .rsvp-btn[aria-pressed="true"][data-ans="yes"] { background:#3F7D5B; border-color:#3F7D5B; color:#fff; }
    .rsvp-btn[aria-pressed="true"][data-ans="no"] { background:var(--n-500); border-color:var(--n-500); color:#fff; }
    .gcal { display:inline-flex; align-items:center; gap:6px; font-size:13px; text-decoration:none;
      color:#2F6FB0; border:1px solid #2F6FB0; border-radius:var(--radius-input); padding:4px 10px;
      transition:background var(--ease); }
    .gcal:hover { background:rgba(47,111,176,0.08); }
    .gcal svg { width:14px; height:14px; }

    /* Save-contact button */
    .hire__head { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:8px; }
    .hire__head .hire__name { margin-bottom:0; }
    .save-btn { appearance:none; font-family:var(--font-sans); font-size:12px; cursor:pointer;
      border:1px solid var(--border-soft); background:var(--white); color:var(--text-body);
      border-radius:999px; padding:4px 10px; display:inline-flex; align-items:center; gap:6px;
      white-space:nowrap; transition:all var(--ease); }
    .save-btn:hover { border-color:var(--border-hover); }
    .save-btn svg { width:14px; height:14px; }
    .save-btn[aria-pressed="true"] { background:var(--gold-500); border-color:var(--gold-500); color:#fff; }

    /* Saved-contacts view */
    .saved-empty { padding:64px 24px; text-align:center; color:var(--text-secondary); font-size:15px; }
    .saved-card { background:var(--white); border:1px solid var(--border-soft);
      border-radius:var(--radius-card); padding:20px 24px; margin-bottom:16px; }
    .saved-card__top { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }
    .saved-card__name { font-size:17px; }
    .saved-card__school { font-size:13px; color:var(--text-secondary); margin-top:2px; }
    .saved-card__fairs { margin-top:12px; font-size:13px; color:var(--text-body); }
    .saved-card__fairs .fairs__title { margin:0 0 6px; }
    .saved-card__fair { display:flex; gap:8px; padding:3px 0; color:var(--text-body); }
    .saved-card__fair b { font-weight:400; color:var(--ink); font-variant-numeric:tabular-nums; white-space:nowrap; }
    .saved-card__none { font-size:13px; color:var(--text-label); font-style:italic; margin-top:10px; }
    .remove-btn { appearance:none; border:1px solid var(--border-soft); background:var(--white);
      color:var(--text-secondary); border-radius:var(--radius-input); font-family:var(--font-sans);
      font-size:13px; cursor:pointer; padding:6px 12px; transition:all var(--ease); white-space:nowrap; }
    .remove-btn:hover { border-color:#B4453C; color:#B4453C; }

    .footnote { margin-top:24px; font-size:12px; color:var(--text-label); }

    @media (max-width:480px) {
      .page { padding:0 16px 64px; }
      .header__label { display:none; }
      .table { background:transparent; border:none; border-radius:0; overflow:visible; }
      .table__head { display:none; }
      .row { grid-template-columns:1fr; gap:8px; padding:16px; background:var(--white);
        border:1px solid var(--border-soft); border-radius:var(--radius-card);
        margin-bottom:16px; min-height:44px; }
      .row__hires { text-align:left; }
      .row__chevron { display:none; }
      .modal__top, .modal__body { padding-left:20px; padding-right:20px; }
    }
    .sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px;
      overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
  </style>
</head>
<body>
  <div class="page">
    <header class="header">
      <div class="header__left">
        <div class="wordmark">
          <span class="wordmark__mark" aria-hidden="true">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="335 2 65 64" fill="none">
              <path d="M370.01 22.5377L378.288 2.55489H370.349L367.228 12.699L364.106 2.55489H356.168L364.446 22.5377H370.01Z" fill="#E19614"/>
              <path d="M364.446 45.1552L356.168 65.1381H364.106L367.228 54.994L370.349 65.1381H378.288L370.01 45.1552H364.446Z" fill="#E19614"/>
              <path d="M355.919 31.0645L335.936 22.7864V30.7252L346.08 33.8465L335.936 36.9677V44.9067L355.919 36.6285V31.0645Z" fill="#E19614"/>
              <path d="M398.519 22.7864L378.536 31.0645V36.6285L398.519 44.9067V36.9677L388.375 33.8465L398.519 30.7252V22.7864Z" fill="#E19614"/>
              <path d="M357.276 39.8741L337.282 48.1636L342.891 53.7728L352.277 48.7971L347.301 58.1832L352.911 63.7924L361.2 43.7984L357.276 39.8741Z" fill="#E19614"/>
              <path d="M377.18 27.8189L397.174 19.5295L391.564 13.9202L382.178 18.8961L387.154 9.50978L381.545 3.90057L373.255 23.8947L377.18 27.8189Z" fill="#E19614"/>
              <path d="M373.255 43.7984L381.545 63.7924L387.154 58.1832L382.178 48.7971L391.564 53.7728L397.174 48.1636L377.18 39.8741L373.255 43.7984Z" fill="#E19614"/>
              <path d="M361.2 23.8947L352.911 3.90057L347.301 9.50978L352.277 18.8961L342.891 13.9202L337.282 19.5295L357.276 27.8189L361.2 23.8947Z" fill="#E19614"/>
            </svg>
          </span>
          <span class="wordmark__name">Valon</span>
        </div>
        <span class="header__divider" aria-hidden="true"></span>
        <span class="header__label">Campus Recruiting</span>
      </div>
    </header>

    <section class="intro">
      <h1>Campus Recruiting Directory</h1>
      <p>Every school Valon has hired from, plus top-100 national universities and
         4-year colleges in New York and San Francisco, with upcoming career fairs.
         Click a school to see who we hired there and how to reach them.</p>
    </section>

    <div class="tabs" role="tablist" aria-label="Views">
      <button class="tab" id="tabDirectory" role="tab" aria-selected="true">Directory</button>
      <button class="tab" id="tabSaved" role="tab" aria-selected="false">
        Saved contacts <span class="tab__count" id="savedCount">0</span>
      </button>
    </div>

    <div id="directoryView">
    <div class="controls">
      <div class="search-row">
        <div class="search">
          <svg class="search__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>
          </svg>
          <input id="search" type="search" placeholder="Search by school name..."
            autocomplete="off" aria-label="Search by school name" />
        </div>
        <button class="filters-btn" id="filtersBtn" type="button" aria-haspopup="true" aria-expanded="false">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"
            stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M3 5h18M6 12h12M10 19h4"/>
          </svg>
          Filters
          <span class="filters-btn__count" id="filterCount" hidden>0</span>
        </button>

        <div class="filter-popup" id="filterPopup" role="dialog" aria-label="Filters" hidden>
          <div class="filter-popup__section">
            <p class="filter-popup__title">Show only schools that have…</p>
            <div class="filters" role="group" aria-label="Category filters">
              <button class="pill" type="button" data-filter="current" aria-pressed="false">Current employees</button>
              <button class="pill" type="button" data-filter="hired" aria-pressed="false">Any hires</button>
              <button class="pill" type="button" data-filter="fair" aria-pressed="false">Upcoming career fair</button>
              <button class="pill" type="button" data-filter="ranked" aria-pressed="false">Top 100</button>
              <button class="pill" type="button" data-filter="ny" aria-pressed="false">New York</button>
              <button class="pill" type="button" data-filter="sf" aria-pressed="false">San Francisco</button>
            </div>
          </div>
          <div class="filter-popup__section">
            <p class="filter-popup__title">Minimum counts</p>
            <label class="filter-field">Min current employees
              <input id="minCurrent" class="filter-input filter-input--num" type="number" min="0" placeholder="0" />
            </label>
            <label class="filter-field">Min hires
              <input id="minHires" class="filter-input filter-input--num" type="number" min="0" placeholder="0" />
            </label>
          </div>
          <div class="filter-popup__section">
            <p class="filter-popup__title">Career fair date</p>
            <div class="filter-daterange">
              <label class="filter-field">From
                <input id="fairFrom" class="filter-input" type="date" />
              </label>
              <label class="filter-field">To
                <input id="fairTo" class="filter-input" type="date" />
              </label>
            </div>
          </div>
          <div class="filter-popup__actions">
            <button class="fbtn fbtn--secondary" id="clearFilters" type="button">Clear all</button>
            <button class="fbtn fbtn--primary" id="doneFilters" type="button">Done</button>
          </div>
        </div>
      </div>
    </div>

    <p class="result-count" id="resultCount" aria-live="polite"></p>

    <div class="table" role="table" aria-label="Campus recruiting directory">
      <div class="table__head" role="row">
        <span class="col-head" role="columnheader">School</span>
        <span class="col-head col-head--hires" role="columnheader">Hires</span>
        <span class="col-head" role="columnheader" aria-hidden="true"></span>
      </div>
      <div id="rows"></div>
      <div class="empty" id="empty" hidden>No schools match your search.</div>
    </div>
    </div><!-- /directoryView -->

    <div id="savedView" hidden>
      <div id="savedList"></div>
      <div class="saved-empty" id="savedEmpty" hidden>
        No saved contacts yet. Open a school, then tap “Save” next to a person to keep them here.
      </div>
    </div>

    <p class="footnote">Ranking source: __RANKING_SOURCE__</p>
  </div>

  <div class="overlay" id="overlay" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
    <div class="modal">
      <div class="modal__top">
        <div>
          <h2 class="modal__title" id="modalTitle">School</h2>
          <div class="modal__meta" id="modalMeta"></div>
        </div>
        <button class="icon-btn" type="button" id="modalClose" aria-label="Close">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"
            stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M6 6l12 12M18 6 6 18"/>
          </svg>
        </button>
      </div>
      <div class="modal__body" id="modalBody"></div>
    </div>
  </div>

  <script>
    const DATA = __DATA__;
    const SCHOOLS = DATA.schools;
    const CRIT = { ranked:"Top 100", ny:"New York", sf:"San Francisco",
                   hired:"Current hire", fair:"Career fair", extra:"Also tracked" };

    // Recompute "upcoming" against today's date on every load, so a fair that
    // has passed drops off without needing the page to be rebuilt.
    const TODAY_ISO = new Date().toISOString().slice(0, 10);
    function upcomingFairs(s) {
      return (s.fairs || []).filter(f => f.date >= TODAY_ISO)
                            .sort((a, b) => a.date < b.date ? -1 : a.date > b.date ? 1 : 0);
    }
    // Single most-recently-passed fair (max 1), recomputed live against today.
    function recentPastFair(s) {
      const past = (s.fairs || []).filter(f => f.date < TODAY_ISO)
                                  .sort((a, b) => a.date < b.date ? 1 : a.date > b.date ? -1 : 0);
      return past[0] || null;
    }
    function fmtDate(iso) {
      const [y, m, d] = iso.split("-").map(Number);
      return new Date(y, m - 1, d).toLocaleDateString("en-US",
        { month: "short", day: "numeric", year: "numeric" });
    }

    // ---- Persistent user state: RSVPs + saved contacts (localStorage) ----
    const LS_KEY = "valon_dir_v1";
    function loadStore() { try { return JSON.parse(localStorage.getItem(LS_KEY)) || {}; } catch (e) { return {}; } }
    let STORE = loadStore();
    STORE.rsvp = STORE.rsvp || {};    // fairKey  -> "yes" | "no"
    STORE.saved = STORE.saved || {};  // contactKey -> {name, school, contacts}
    function persist() { try { localStorage.setItem(LS_KEY, JSON.stringify(STORE)); } catch (e) {} }
    const fairKey = (school, f) => `${school}||${f.date}||${f.name}`;
    const contactKey = (school, name) => `${school}||${name}`;

    // Google Calendar "add event" prefilled URL — all-day, no auth required.
    function gcalUrl(school, f) {
      const [y, m, d] = f.date.split("-");
      const start = `${y}${m}${d}`;
      const dt = new Date(Date.UTC(+y, +m - 1, +d)); dt.setUTCDate(dt.getUTCDate() + 1);
      const end = `${dt.getUTCFullYear()}${String(dt.getUTCMonth() + 1).padStart(2, "0")}${String(dt.getUTCDate()).padStart(2, "0")}`;
      const details = `${school} career fair.` + (f.source ? `\nSource: ${f.source}` : "");
      const p = new URLSearchParams({ action: "TEMPLATE", text: `${f.name} — ${school}`,
        dates: `${start}/${end}`, details, location: f.location || school });
      return "https://calendar.google.com/calendar/render?" + p.toString();
    }
    function bookmarkIcon() {
      const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("fill", "none");
      s.setAttribute("stroke", "currentColor"); s.setAttribute("stroke-width", "1.5");
      s.setAttribute("stroke-linecap", "round"); s.setAttribute("stroke-linejoin", "round");
      const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      p.setAttribute("d", "M6 3h12a1 1 0 0 1 1 1v17l-7-4-7 4V4a1 1 0 0 1 1-1z"); s.appendChild(p);
      return s;
    }

    const rowsEl = document.getElementById("rows");
    const emptyEl = document.getElementById("empty");
    const countEl = document.getElementById("resultCount");

    let query = "";
    const active = new Set();          // category toggles
    let minCurrent = 0, minHires = 0;  // minimum counts
    let fairFrom = "", fairTo = "";    // career-fair date range (ISO)

    function currentCount(s) { return (s.hires || []).filter(h => h.current).length; }

    function matches(s) {
      const q = query.trim().toLowerCase();
      if (q && !s.name.toLowerCase().includes(q)) return false;
      for (const f of active) {
        if (f === "fair") { if (!upcomingFairs(s).length) return false; }
        else if (f === "current") { if (currentCount(s) < 1) return false; }
        else if (!s.criteria.includes(f)) return false;
      }
      if (minCurrent > 0 && currentCount(s) < minCurrent) return false;
      if (minHires > 0 && s.count < minHires) return false;
      if (fairFrom || fairTo) {
        const inRange = (s.fairs || []).some(fr =>
          (!fairFrom || fr.date >= fairFrom) && (!fairTo || fr.date <= fairTo));
        if (!inRange) return false;
      }
      return true;
    }

    function activeFilterCount() {
      return active.size + (minCurrent > 0 ? 1 : 0) + (minHires > 0 ? 1 : 0)
             + ((fairFrom || fairTo) ? 1 : 0);
    }

    function tag(kind) {
      const el = document.createElement("span");
      el.className = "tag tag--" + kind;
      el.textContent = CRIT[kind];
      return el;
    }
    function chevron() {
      const s = document.createElementNS("http://www.w3.org/2000/svg","svg");
      s.setAttribute("viewBox","0 0 24 24"); s.setAttribute("fill","none");
      s.setAttribute("stroke","currentColor"); s.setAttribute("stroke-width","1.5");
      s.setAttribute("stroke-linecap","round"); s.setAttribute("stroke-linejoin","round");
      const p = document.createElementNS("http://www.w3.org/2000/svg","path");
      p.setAttribute("d","m9 6 6 6-6 6"); s.appendChild(p);
      const wrap = document.createElement("span"); wrap.className="row__chevron";
      wrap.appendChild(s); return wrap;
    }
    function calIcon() {
      const s = document.createElementNS("http://www.w3.org/2000/svg","svg");
      s.setAttribute("viewBox","0 0 24 24"); s.setAttribute("fill","none");
      s.setAttribute("stroke","currentColor"); s.setAttribute("stroke-width","1.5");
      s.setAttribute("stroke-linecap","round"); s.setAttribute("stroke-linejoin","round");
      for (const d of ["M8 2v4","M16 2v4","M3 9h18"]) {
        const p = document.createElementNS("http://www.w3.org/2000/svg","path");
        p.setAttribute("d", d); s.appendChild(p);
      }
      const r = document.createElementNS("http://www.w3.org/2000/svg","rect");
      r.setAttribute("x","3"); r.setAttribute("y","4"); r.setAttribute("width","18");
      r.setAttribute("height","18"); r.setAttribute("rx","2"); s.appendChild(r);
      return s;
    }

    function render() {
      const list = SCHOOLS.filter(matches);
      rowsEl.textContent = "";
      list.forEach(s => {
        const btn = document.createElement("button");
        btn.type = "button"; btn.className = "row"; btn.setAttribute("role","row");
        btn.setAttribute("aria-label", `${s.name}, ${s.count} hires`);

        const main = document.createElement("span");
        main.className = "row__main";

        const nameWrap = document.createElement("span");
        nameWrap.className = "row__name-wrap";
        const nm = document.createElement("span");
        nm.className = "row__name"; nm.textContent = s.name;
        nameWrap.appendChild(nm);
        if (s.criteria.includes("ranked")) nameWrap.appendChild(tag("ranked"));
        if (s.criteria.includes("ny")) nameWrap.appendChild(tag("ny"));
        if (s.criteria.includes("sf")) nameWrap.appendChild(tag("sf"));
        if (s.criteria.includes("hired")) nameWrap.appendChild(tag("hired"));
        main.appendChild(nameWrap);

        const nextFair = upcomingFairs(s)[0];
        if (nextFair) {
          const sub = document.createElement("span");
          sub.className = "row__sub";
          sub.appendChild(calIcon());
          const dt = document.createElement("b"); dt.textContent = fmtDate(nextFair.date);
          const nmn = document.createElement("span");
          nmn.className = "row__sub-name"; nmn.textContent = " · " + nextFair.name;
          sub.appendChild(dt); sub.appendChild(nmn);
          main.appendChild(sub);
        }

        const hires = document.createElement("span");
        hires.className = "row__hires";
        hires.textContent = s.count === 0 ? "No hires yet"
                          : `${s.count} hire${s.count === 1 ? "" : "s"}`;

        btn.appendChild(main);
        btn.appendChild(hires);
        btn.appendChild(chevron());
        btn.addEventListener("click", () => openDetail(s));
        rowsEl.appendChild(btn);
      });
      emptyEl.hidden = list.length !== 0;
      countEl.textContent = `${list.length} of ${SCHOOLS.length} schools`;
    }

    // Modal
    const overlay = document.getElementById("overlay");
    const modalBody = document.getElementById("modalBody");
    const modalMeta = document.getElementById("modalMeta");
    let lastFocused = null;

    // ---- Email template picker ----
    function buildMailto(email, subject, body) {
      let u = "mailto:" + email;
      const parts = [];
      if (subject) parts.push("subject=" + encodeURIComponent(subject));
      if (body) parts.push("body=" + encodeURIComponent(body.replace(/\n/g, "\r\n")));
      return parts.length ? u + "?" + parts.join("&") : u;
    }
    function emailTemplates(ctx) {
      const raw = (ctx.name || "").trim();
      const fn = (raw && raw[0] !== "(") ? raw.split(/\s+/)[0] : "there";
      const school = ctx.school || "your school";
      return [
        { label: "Invitation", hint: "Invite them to connect",
          subject: "Connecting with Valon",
          body: `Hi ${fn},\n\nI'm on the campus recruiting team at Valon. Your background at ${school} stood out, and I'd love to invite you to connect — a quick call, a coffee chat, or to meet our team at an upcoming career fair.\n\nWould you be open to a short conversation over the next week or two?\n\nBest,\n[Your name]\nValon | Campus Recruiting` },
        { label: "Inquiry about the institution", hint: "Ask about recruiting at their school",
          subject: `Quick question about ${school}`,
          body: `Hi ${fn},\n\nI'm reaching out from Valon's campus recruiting team. We're looking to grow our presence at ${school}, and since you know the community well, I'd value your perspective — which career fairs are worth attending, active student organizations, and how best to reach strong candidates there.\n\nWould you have 15 minutes to share your thoughts?\n\nBest,\n[Your name]\nValon | Campus Recruiting` },
        { label: "Other", hint: "Blank email — write your own",
          subject: "", body: "" },
      ];
    }
    let emailMenuEl = null;
    function closeEmailMenu() {
      if (emailMenuEl) { emailMenuEl.remove(); emailMenuEl = null; }
      document.removeEventListener("click", onDocClickEmail, true);
    }
    function onDocClickEmail(e) { if (emailMenuEl && !emailMenuEl.contains(e.target)) closeEmailMenu(); }
    function openEmailMenu(anchor, c, ctx) {
      closeEmailMenu();
      const menu = document.createElement("div"); menu.className = "email-menu";
      const t = document.createElement("div"); t.className = "email-menu__title";
      t.textContent = "Email " + c.value; menu.appendChild(t);
      emailTemplates(ctx || {}).forEach(tpl => {
        const b = document.createElement("button"); b.type = "button"; b.className = "email-menu__item";
        b.textContent = tpl.label;
        const s = document.createElement("small"); s.textContent = tpl.hint; b.appendChild(s);
        b.addEventListener("click", () => {
          window.location.href = buildMailto(c.value, tpl.subject, tpl.body);
          closeEmailMenu();
        });
        menu.appendChild(b);
      });
      document.body.appendChild(menu);
      const r = anchor.getBoundingClientRect();
      menu.style.position = "fixed";
      menu.style.top = Math.min(r.bottom + 6, window.innerHeight - menu.offsetHeight - 10) + "px";
      menu.style.left = Math.min(r.left, window.innerWidth - menu.offsetWidth - 10) + "px";
      emailMenuEl = menu;
      setTimeout(() => document.addEventListener("click", onDocClickEmail, true), 0);
    }

    function contactChip(c, ctx) {
      if (c.kind === "email") {
        const btn = document.createElement("button");
        btn.type = "button"; btn.className = "contact contact--mono";
        const lab = document.createElement("span");
        lab.className = "contact__label"; lab.textContent = c.label;
        const val = document.createElement("span");
        val.className = "contact__value"; val.textContent = c.value;
        btn.appendChild(lab); btn.appendChild(val);
        btn.addEventListener("click", (e) => { e.stopPropagation(); openEmailMenu(btn, c, ctx || {}); });
        return btn;
      }
      const a = document.createElement("a");
      a.className = "contact";
      a.href = c.href; a.target = "_blank"; a.rel = "noopener";
      const lab = document.createElement("span");
      lab.className = "contact__label"; lab.textContent = c.label;
      const val = document.createElement("span");
      val.className = "contact__value"; val.textContent = c.value;
      a.appendChild(lab); a.appendChild(val);
      return a;
    }

    function openDetail(s) {
      lastFocused = document.activeElement;
      document.getElementById("modalTitle").textContent = s.name;

      modalMeta.textContent = "";
      const hc = document.createElement("span");
      hc.textContent = s.count === 0 ? "No hires yet"
                     : `${s.count} hire${s.count === 1 ? "" : "s"}`;
      modalMeta.appendChild(hc);
      ["ranked","ny","sf","extra","hired"].forEach(k => {
        if (s.criteria.includes(k)) {
          const sep = document.createElement("span"); sep.textContent = "·"; sep.setAttribute("aria-hidden","true");
          modalMeta.appendChild(sep); modalMeta.appendChild(tag(k));
        }
      });

      modalBody.textContent = "";

      // Build a single .fair row element (shared by upcoming + passed).
      function fairRow(f, allowRsvp) {
        const [y, m, d] = f.date.split("-").map(Number);
        const row = document.createElement("div"); row.className = "fair";
        const dbox = document.createElement("div"); dbox.className = "fair__date";
        const mm = document.createElement("div"); mm.className = "fair__date-m";
        mm.textContent = new Date(y, m - 1, d).toLocaleDateString("en-US", { month: "short" });
        const dd = document.createElement("div"); dd.className = "fair__date-d"; dd.textContent = d;
        const yy = document.createElement("div"); yy.className = "fair__date-y"; yy.textContent = y;
        dbox.appendChild(mm); dbox.appendChild(dd); dbox.appendChild(yy);
        const body = document.createElement("div"); body.className = "fair__body";
        const fn = document.createElement("div"); fn.className = "fair__name"; fn.textContent = f.name;
        body.appendChild(fn);
        if (f.location) {
          const lc = document.createElement("div"); lc.className = "fair__loc"; lc.textContent = f.location;
          body.appendChild(lc);
        }
        if (f.source) {
          const sc = document.createElement("div"); sc.className = "fair__src";
          const a = document.createElement("a"); a.href = f.source; a.target = "_blank";
          a.rel = "noopener"; a.textContent = "Source / register";
          sc.appendChild(a); body.appendChild(sc);
        }

        // "Planning to attend?" RSVP + add-to-Google-Calendar (upcoming only).
        if (allowRsvp) {
          const key = fairKey(s.name, f);
          const rsvp = document.createElement("div"); rsvp.className = "fair__rsvp";
          const q = document.createElement("span"); q.className = "fair__rsvp-q";
          q.textContent = "Planning to attend?";
          const yes = document.createElement("button");
          yes.type = "button"; yes.className = "rsvp-btn"; yes.dataset.ans = "yes"; yes.textContent = "Yes";
          const no = document.createElement("button");
          no.type = "button"; no.className = "rsvp-btn"; no.dataset.ans = "no"; no.textContent = "No";
          const gcal = document.createElement("a"); gcal.className = "gcal";
          gcal.href = gcalUrl(s.name, f); gcal.target = "_blank"; gcal.rel = "noopener";
          gcal.appendChild(calIcon());
          const gt = document.createElement("span"); gt.textContent = "Add to Google Calendar";
          gcal.appendChild(gt);
          const reflect = () => {
            const v = STORE.rsvp[key];
            yes.setAttribute("aria-pressed", String(v === "yes"));
            no.setAttribute("aria-pressed", String(v === "no"));
            gcal.style.display = v === "yes" ? "inline-flex" : "none";
          };
          const setAns = (ans) => {
            if (STORE.rsvp[key] === ans) delete STORE.rsvp[key];
            else STORE.rsvp[key] = ans;
            persist(); reflect();
          };
          yes.addEventListener("click", () => {
            setAns("yes");
            if (STORE.rsvp[key] === "yes") window.open(gcal.href, "_blank", "noopener");
          });
          no.addEventListener("click", () => setAns("no"));
          rsvp.appendChild(q); rsvp.appendChild(yes); rsvp.appendChild(no); rsvp.appendChild(gcal);
          body.appendChild(rsvp);
          reflect();
        }

        row.appendChild(dbox); row.appendChild(body);
        return row;
      }

      // Upcoming career fairs (recomputed against today).
      const fairs = upcomingFairs(s);
      if (fairs.length) {
        const wrap = document.createElement("div"); wrap.className = "fairs";
        const t = document.createElement("p"); t.className = "fairs__title";
        t.textContent = `Upcoming career fair${fairs.length === 1 ? "" : "s"} (${fairs.length})`;
        wrap.appendChild(t);
        fairs.forEach(f => wrap.appendChild(fairRow(f, true)));
        modalBody.appendChild(wrap);
      }

      // Recently passed — at most ONE (the most recent), recomputed live.
      const past = recentPastFair(s);
      if (past) {
        const wrap = document.createElement("div"); wrap.className = "fairs fairs--past";
        const t = document.createElement("p"); t.className = "fairs__title";
        t.textContent = "Recently passed";
        wrap.appendChild(t);
        wrap.appendChild(fairRow(past, false));
        modalBody.appendChild(wrap);
      }
      if (!s.hires.length) {
        const e = document.createElement("div");
        e.className = "modal__emptystate";
        const parts = [];
        if (s.criteria.includes("ranked")) parts.push("a top-100 national university");
        if (s.criteria.includes("ny")) parts.push("a New York State institution");
        if (s.criteria.includes("sf")) parts.push("a San Francisco institution");
        if (s.criteria.includes("extra")) parts.push("tracked for career-fair coverage");
        e.textContent = "No hires from this school yet — it's a target because it's "
          + (parts.join(" and ") || "in scope") + ".";
        modalBody.appendChild(e);
      } else {
        const hireRow = (h) => {
          const row = document.createElement("div"); row.className = "hire";
          const head = document.createElement("div"); head.className = "hire__head";
          const nm = document.createElement("div"); nm.className = "hire__name";
          nm.textContent = h.name || "(name unavailable)";
          head.appendChild(nm);
          // Save-contact toggle (persists to the Saved tab).
          const key = contactKey(s.name, h.name || "");
          const save = document.createElement("button");
          save.type = "button"; save.className = "save-btn";
          save.appendChild(bookmarkIcon());
          const lbl = document.createElement("span"); save.appendChild(lbl);
          const reflectSave = () => {
            const on = !!STORE.saved[key];
            save.setAttribute("aria-pressed", String(on));
            lbl.textContent = on ? "Saved" : "Save";
          };
          save.addEventListener("click", () => {
            if (STORE.saved[key]) delete STORE.saved[key];
            else STORE.saved[key] = { name: h.name || "(name unavailable)",
                                      school: s.name, contacts: h.contacts || [] };
            persist(); reflectSave(); updateSavedCount();
          });
          reflectSave();
          head.appendChild(save);
          row.appendChild(head);
          if (h.contacts.length) {
            const cc = document.createElement("div"); cc.className = "contacts";
            h.contacts.forEach(c => cc.appendChild(contactChip(c, { name: h.name, school: s.name })));
            row.appendChild(cc);
          } else {
            const none = document.createElement("div");
            none.className = "hire__none"; none.textContent = "No contact info available";
            row.appendChild(none);
          }
          return row;
        };
        const hireGroup = (title, list) => {
          if (!list.length) return;
          const g = document.createElement("div"); g.className = "hire-group";
          const t = document.createElement("p"); t.className = "hire-group__title";
          t.textContent = `${title} (${list.length})`;
          g.appendChild(t);
          list.forEach(h => g.appendChild(hireRow(h)));
          modalBody.appendChild(g);
        };
        // Current employees first, then past hires.
        hireGroup("Current Employees", s.hires.filter(h => h.current));
        hireGroup("Past Hires", s.hires.filter(h => !h.current));
      }
      overlay.classList.add("open");
      document.getElementById("modalClose").focus();
    }
    function closeDetail() { closeEmailMenu(); overlay.classList.remove("open"); if (lastFocused) lastFocused.focus(); }

    document.getElementById("modalClose").addEventListener("click", closeDetail);
    overlay.addEventListener("click", e => { if (e.target === overlay) closeDetail(); });
    document.addEventListener("keydown", e => {
      if (e.key === "Escape" && overlay.classList.contains("open")) closeDetail();
    });

    function updateFilterCount() {
      const n = activeFilterCount();
      const badge = document.getElementById("filterCount");
      badge.textContent = n; badge.hidden = n === 0;
    }
    const rerender = () => { updateFilterCount(); render(); };

    document.getElementById("search").addEventListener("input", e => { query = e.target.value; render(); });

    document.querySelectorAll(".pill").forEach(p => {
      p.addEventListener("click", () => {
        const f = p.dataset.filter;
        const on = p.getAttribute("aria-pressed") === "true";
        p.setAttribute("aria-pressed", String(!on));
        if (on) active.delete(f); else active.add(f);
        rerender();
      });
    });
    document.getElementById("minCurrent").addEventListener("input", e => { minCurrent = parseInt(e.target.value, 10) || 0; rerender(); });
    document.getElementById("minHires").addEventListener("input", e => { minHires = parseInt(e.target.value, 10) || 0; rerender(); });
    document.getElementById("fairFrom").addEventListener("input", e => { fairFrom = e.target.value; rerender(); });
    document.getElementById("fairTo").addEventListener("input", e => { fairTo = e.target.value; rerender(); });

    // Filters popup open/close
    const popup = document.getElementById("filterPopup");
    const fbtn = document.getElementById("filtersBtn");
    function togglePopup(show) {
      const open = show === undefined ? popup.hidden : show;
      popup.hidden = !open;
      fbtn.setAttribute("aria-expanded", String(open));
    }
    fbtn.addEventListener("click", e => { e.stopPropagation(); togglePopup(); });
    popup.addEventListener("click", e => e.stopPropagation());
    document.addEventListener("click", () => { if (!popup.hidden) togglePopup(false); });
    document.getElementById("doneFilters").addEventListener("click", () => togglePopup(false));
    document.addEventListener("keydown", e => { if (e.key === "Escape" && !popup.hidden) togglePopup(false); });

    document.getElementById("clearFilters").addEventListener("click", () => {
      active.clear(); minCurrent = 0; minHires = 0; fairFrom = ""; fairTo = "";
      document.querySelectorAll(".pill").forEach(p => p.setAttribute("aria-pressed", "false"));
      ["minCurrent", "minHires", "fairFrom", "fairTo"].forEach(id => document.getElementById(id).value = "");
      rerender();
    });

    // ---- Saved-contacts tab ----
    function updateSavedCount() {
      document.getElementById("savedCount").textContent = Object.keys(STORE.saved).length;
    }
    function renderSaved() {
      const listEl = document.getElementById("savedList");
      const emptyEl2 = document.getElementById("savedEmpty");
      listEl.textContent = "";
      const entries = Object.entries(STORE.saved);
      emptyEl2.hidden = entries.length !== 0;
      entries.sort((a, b) => (a[1].school + a[1].name).localeCompare(b[1].school + b[1].name));
      entries.forEach(([key, c]) => {
        const card = document.createElement("div"); card.className = "saved-card";
        const top = document.createElement("div"); top.className = "saved-card__top";
        const info = document.createElement("div");
        const nm = document.createElement("div"); nm.className = "saved-card__name"; nm.textContent = c.name;
        const sch = document.createElement("div"); sch.className = "saved-card__school"; sch.textContent = c.school;
        info.appendChild(nm); info.appendChild(sch);
        const rm = document.createElement("button"); rm.type = "button"; rm.className = "remove-btn"; rm.textContent = "Remove";
        rm.addEventListener("click", () => { delete STORE.saved[key]; persist(); updateSavedCount(); renderSaved(); });
        top.appendChild(info); top.appendChild(rm);
        card.appendChild(top);
        if (c.contacts && c.contacts.length) {
          const cc = document.createElement("div"); cc.className = "contacts"; cc.style.marginTop = "10px";
          c.contacts.forEach(x => cc.appendChild(contactChip(x, { name: c.name, school: c.school })));
          card.appendChild(cc);
        }
        const school = SCHOOLS.find(x => x.name === c.school);
        const ups = school ? upcomingFairs(school) : [];
        const fw = document.createElement("div"); fw.className = "saved-card__fairs";
        if (ups.length) {
          const ttl = document.createElement("p"); ttl.className = "fairs__title";
          ttl.textContent = `${c.school} — upcoming career fair${ups.length === 1 ? "" : "s"}`;
          fw.appendChild(ttl);
          ups.forEach(f => {
            const r = document.createElement("div"); r.className = "saved-card__fair";
            const b = document.createElement("b"); b.textContent = fmtDate(f.date);
            const n = document.createElement("span"); n.textContent = "· " + f.name;
            r.appendChild(b); r.appendChild(n); fw.appendChild(r);
          });
          card.appendChild(fw);
        } else {
          const none = document.createElement("div"); none.className = "saved-card__none";
          none.textContent = `No upcoming career fairs listed for ${c.school}.`;
          card.appendChild(none);
        }
        listEl.appendChild(card);
      });
    }
    const dirView = document.getElementById("directoryView");
    const savView = document.getElementById("savedView");
    const tabDir = document.getElementById("tabDirectory");
    const tabSav = document.getElementById("tabSaved");
    function showTab(saved) {
      closeEmailMenu();
      tabSav.setAttribute("aria-selected", String(saved));
      tabDir.setAttribute("aria-selected", String(!saved));
      savView.hidden = !saved; dirView.hidden = saved;
      if (saved) renderSaved();
    }
    tabDir.addEventListener("click", () => showTab(false));
    tabSav.addEventListener("click", () => showTab(true));

    updateSavedCount();
    updateFilterCount();
    render();
  </script>
</body>
</html>
"""
