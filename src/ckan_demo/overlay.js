/**
 * Injected into every page: a pointer and click ripples (Playwright's video
 * has none), the caption bar, title cards, and CSS hiding CKAN's dev chrome.
 */
(() => {
    if (window.__demo) return;

    const css = `
        .debug, #flDebug { display: none !important; }

        /* Hidden in screenshots (Director.screenshot). */
        html.demo-screenshot #demo-cursor,
        html.demo-screenshot #demo-caption,
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
        #demo-caption.shown { opacity: 1; transform: translate(-50%, 0); }

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

    let cursor, caption, card;

    function mount() {
        const style = document.createElement("style");
        style.textContent = css;
        document.head.appendChild(style);

        cursor = document.createElement("div");
        cursor.id = "demo-cursor";
        cursor.innerHTML = cursorSvg;
        caption = document.createElement("div");
        caption.id = "demo-caption";
        card = document.createElement("div");
        card.id = "demo-card";
        document.body.append(cursor, caption, card);

        // Restore the pointer position from the previous page.
        const last = JSON.parse(sessionStorage.getItem("demo-cursor") || "null");
        if (last) move(last.x, last.y);
    }

    function move(x, y) {
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

    window.__demo = {
        caption(text) {
            if (!text) {
                caption.classList.remove("shown");
                return;
            }
            caption.textContent = text;
            caption.classList.add("shown");
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
