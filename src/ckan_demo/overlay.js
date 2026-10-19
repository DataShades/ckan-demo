/**
 * Injected into every page: a pointer and click ripples (Playwright's video
 * has none), the caption bar, key badges, title cards, the spotlight, and CSS
 * hiding CKAN's dev chrome.
 */
(() => {
    if (window.__demo) return;

    const css = `
        .debug, #flDebug { display: none !important; }

        /* Hidden in screenshots (Director.screenshot). */
        html.demo-screenshot #demo-cursor,
        html.demo-screenshot #demo-caption,
        html.demo-screenshot #demo-card,
        html.demo-screenshot #demo-keys,
        html.demo-screenshot #demo-spotlight,
        html.demo-screenshot .demo-ripple { display: none !important; }

        #demo-cursor {
            position: fixed; z-index: 2147483647; left: 0; top: 0;
            width: 22px; height: 22px; margin: -3px 0 0 -3px;
            pointer-events: none;
            transition: transform 0.08s ease-out;
        }
        #demo-cursor.down { transform: scale(0.85); }

        .demo-ripple {
            position: fixed; z-index: 2147483646; pointer-events: none;
            width: 36px; height: 36px; margin: -18px 0 0 -18px; border-radius: 50%;
            border: 3px solid rgba(37, 99, 235, 0.85);
            animation: demo-ripple 0.5s ease-out forwards;
        }
        @keyframes demo-ripple {
            from { transform: scale(0.3); opacity: 1; }
            to   { transform: scale(1.6); opacity: 0; }
        }

        #demo-caption {
            position: fixed; z-index: 2147483645; left: 50%; bottom: 40px;
            transform: translate(-50%, 12px); opacity: 0;
            max-width: 70%; padding: 14px 26px; border-radius: 14px;
            background: rgba(15, 23, 42, 0.92); color: #f8fafc;
            font: 600 22px/1.35 "Noto Sans", system-ui, sans-serif; text-align: center;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
            transition: opacity 0.3s ease, transform 0.3s ease;
            pointer-events: none;
        }
        #demo-caption.top { top: 40px; bottom: auto; transform: translate(-50%, -12px); }
        #demo-caption.shown { opacity: 1; transform: translate(-50%, 0); }

        #demo-keys {
            position: fixed; z-index: 2147483645; left: 50%; bottom: 40px;
            display: flex; align-items: center; gap: 8px;
            transform: translate(-50%, 8px); opacity: 0;
            padding: 10px 16px; border-radius: 12px;
            background: rgba(15, 23, 42, 0.92); color: #cbd5e1;
            font: 600 20px/1 "Noto Sans", system-ui, sans-serif;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
            transition: opacity 0.2s ease, transform 0.2s ease;
            pointer-events: none;
        }
        #demo-keys.shown { opacity: 1; transform: translate(-50%, 0); }
        #demo-keys kbd {
            min-width: 20px; padding: 7px 11px; border-radius: 7px; text-align: center;
            background: #f8fafc; color: #0f172a; font: inherit;
            box-shadow: inset 0 -3px 0 #cbd5e1;
        }

        /* A hole over the element; its shadow dims the rest of the page. */
        #demo-spotlight {
            position: fixed; z-index: 2147483643; left: 0; top: 0; width: 0; height: 0;
            border-radius: 10px; pointer-events: none;
            box-shadow: 0 0 0 200vmax rgba(15, 23, 42, 0.6);
            opacity: 0; transition: opacity 0.35s ease;
        }
        #demo-spotlight.shown { opacity: 1; }

        #demo-card {
            position: fixed; z-index: 2147483644; inset: 0;
            display: flex; flex-direction: column; align-items: center; justify-content: center;
            gap: 18px; padding: 0 10%;
            background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%); color: #f8fafc;
            font-family: "Noto Sans", system-ui, sans-serif; text-align: center;
            opacity: 0; transition: opacity 0.4s ease; pointer-events: none;
        }
        #demo-card.shown { opacity: 1; }
        #demo-card .kicker { font-size: 20px; letter-spacing: 0.18em; text-transform: uppercase; color: #93c5fd; }
        #demo-card h1 { margin: 0; font-size: 64px; font-weight: 800; color: inherit; }
        #demo-card p { margin: 0; font-size: 26px; color: #cbd5e1; max-width: 900px; }
    `;

    const cursorSvg = `
        <svg viewBox="0 0 24 24" width="22" height="22" xmlns="http://www.w3.org/2000/svg">
            <path d="M3 2 L3 19 L8 14.5 L11.5 22 L14.5 20.6 L11 13.3 L17.5 13.3 Z"
                  fill="#111827" stroke="#ffffff" stroke-width="1.6" stroke-linejoin="round"/>
        </svg>`;

    let cursor, caption, keys, card, spotlight;
    let keysHide = null;  // pending fade-out of the key badge
    let pointer = null;  // last pointer position
    let captionMode = "bottom";  // "top", "bottom" or "auto"
    let captionMove = null;  // pending move to the other edge

    function mount() {
        const style = document.createElement("style");
        style.textContent = css;
        document.head.appendChild(style);

        cursor = document.createElement("div");
        cursor.id = "demo-cursor";
        cursor.innerHTML = cursorSvg;
        caption = document.createElement("div");
        caption.id = "demo-caption";
        keys = document.createElement("div");
        keys.id = "demo-keys";
        card = document.createElement("div");
        card.id = "demo-card";
        spotlight = document.createElement("div");
        spotlight.id = "demo-spotlight";
        document.body.append(cursor, caption, keys, card, spotlight);

        // Restore the pointer position from the previous page.
        const last = JSON.parse(sessionStorage.getItem("demo-cursor") || "null");
        if (last) move(last.x, last.y);
    }

    function move(x, y) {
        pointer = { x, y, width: 22, height: 22 };
        cursor.style.left = x + "px";
        cursor.style.top = y + "px";
        sessionStorage.setItem("demo-cursor", JSON.stringify({ x, y }));
    }

    document.addEventListener("mousemove", (e) => cursor && move(e.clientX, e.clientY), true);
    document.addEventListener("mousedown", (e) => {
        if (!cursor) return;
        cursor.classList.add("down");
        const ripple = document.createElement("div");
        ripple.className = "demo-ripple";
        ripple.style.left = e.clientX + "px";
        ripple.style.top = e.clientY + "px";
        document.body.appendChild(ripple);
        setTimeout(() => ripple.remove(), 600);
    }, true);
    document.addEventListener("mouseup", () => cursor && cursor.classList.remove("down"), true);

    const escape = (text) => {
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    };

    // ── Caption position ─────────────────────────────────────────────────

    const GAP = 16;  // clearance kept between a caption and what it avoids

    function edgeOf() {
        return caption.classList.contains("top") ? "top" : "bottom";
    }

    // Where the caption is, or would be at `edge`, in viewport pixels.
    function captionRect(edge) {
        const rect = caption.getBoundingClientRect();
        const height = rect.height;
        const top = edge === "top" ? 40 : window.innerHeight - 40 - height;
        return { left: rect.left, right: rect.right, top, bottom: top + height };
    }

    function covers(box, edge) {
        if (!box) return false;
        const rect = captionRect(edge);
        return box.x < rect.right + GAP && box.x + box.width > rect.left - GAP
            && box.y < rect.bottom + GAP && box.y + box.height > rect.top - GAP;
    }

    // Put the caption at `edge`; a visible one fades out and back in there.
    function place(edge) {
        clearTimeout(captionMove);
        captionMove = null;
        if (edgeOf() === edge) return;
        if (!caption.classList.contains("shown")) {
            caption.classList.toggle("top", edge === "top");
            return;
        }
        caption.classList.remove("shown");
        captionMove = setTimeout(() => {
            caption.classList.toggle("top", edge === "top");
            caption.classList.add("shown");
            captionMove = null;
        }, 300);
    }

    // ── Scrolling ────────────────────────────────────────────────────────

    // Ease in and out, like the pointer (minimum jerk).
    const ease = (t) => t * t * t * (10 - 15 * t + 6 * t * t);

    window.__demo = {
        caption(text, position = "bottom") {
            if (!text) {
                clearTimeout(captionMove);
                captionMove = null;
                caption.classList.remove("shown");
                return;
            }
            captionMode = position;
            caption.textContent = text;
            // Auto starts at the bottom, unless the pointer is already there.
            const edge = position === "top" || (position === "auto" && covers(pointer, "bottom")) ? "top" : "bottom";
            place(edge);
            if (!captionMove) caption.classList.add("shown");
        },
        // Before the pointer goes to `box`: an auto caption that would cover
        // it moves to the other edge, if that one is clear.
        avoid(box) {
            if (captionMode !== "auto" || !caption.classList.contains("shown") || captionMove) return;
            const edge = edgeOf();
            const other = edge === "top" ? "bottom" : "top";
            if (covers(box, edge) && !covers(box, other)) place(other);
        },
        // A badge of keycaps, e.g. ["Ctrl", "Enter"], for `ms` milliseconds:
        // just above a bottom caption, below a top one, else at the bottom.
        keys(caps, ms) {
            clearTimeout(keysHide);
            keys.innerHTML = caps.map((cap) => `<kbd>${escape(cap)}</kbd>`).join("<span>+</span>");
            keys.style.top = keys.style.bottom = "";
            if (caption.classList.contains("shown")) {
                const rect = caption.getBoundingClientRect();
                if (edgeOf() === "top") {
                    keys.style.top = rect.bottom + 12 + "px";
                    keys.style.bottom = "auto";
                } else {
                    keys.style.bottom = window.innerHeight - rect.top + 12 + "px";
                }
            }
            keys.classList.add("shown");
            keysHide = setTimeout(() => keys.classList.remove("shown"), ms);
        },
        // Dim everything but `box` (viewport pixels), `padding` px around it;
        // no box fades the dimming out.
        spotlight(box, padding = 8) {
            if (!box) {
                spotlight.classList.remove("shown");
                return;
            }
            Object.assign(spotlight.style, {
                left: box.x - padding + "px",
                top: box.y - padding + "px",
                width: box.width + 2 * padding + "px",
                height: box.height + 2 * padding + "px",
            });
            spotlight.classList.add("shown");
        },
        // Scroll the page so `el` is centred, smoothly, unless it's already in
        // view. Resolves with the pixels scrolled once the page is still.
        // `scroll-behavior: smooth` (Bootstrap sets it) is bypassed, so
        // timing is ours and follows `speed`.
        reveal(el, speed = 1) {
            const rect = el.getBoundingClientRect();
            const height = window.innerHeight;
            if (rect.top >= 0 && rect.bottom <= height) return Promise.resolve(0);

            const from = window.scrollY;
            const max = document.documentElement.scrollHeight - height;
            // Centred, or the top just below the edge if it's taller than the view.
            const offset = rect.height > height - 160 ? rect.top - 80 : rect.top + rect.height / 2 - height / 2;
            const to = Math.max(0, Math.min(max, from + offset));
            const distance = Math.abs(to - from);
            if (distance < 1) return Promise.resolve(0);

            const ms = (350 + 150 * Math.log2(1 + distance / 200)) / speed;
            return new Promise((resolve) => {
                const start = performance.now();
                const step = (now) => {
                    const t = Math.min(1, (now - start) / ms);
                    window.scrollTo({ top: from + (to - from) * ease(t), behavior: "instant" });
                    if (t < 1) requestAnimationFrame(step);
                    else requestAnimationFrame(() => resolve(distance));
                };
                requestAnimationFrame(step);
            });
        },
        card(kicker, title, text) {
            if (!title) {
                card.classList.remove("shown");
                return;
            }
            card.innerHTML =
                (kicker ? `<div class="kicker">${escape(kicker)}</div>` : "") +
                `<h1>${escape(title)}</h1>` +
                (text ? `<p>${escape(text)}</p>` : "");
            card.classList.add("shown");
        },
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", mount);
    } else {
        mount();
    }
})();
