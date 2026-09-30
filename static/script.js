/* =============================================================
   LearnHub — client interactions
   (Theme is set pre-paint by the inline snippet in base.html;
   this file wires up the toggle button and everything else.)
   ============================================================= */

var LH = window.LH || {};

document.addEventListener("DOMContentLoaded", function () {

    /* -----------------------------------------------------------
       Highlight the active bottom-nav item based on current path
       ----------------------------------------------------------- */
    var navLinks = document.querySelectorAll(".bottom-nav a");
    var path = window.location.pathname;

    navLinks.forEach(function (link) {
        var href = link.getAttribute("href");
        if (href === path || (href !== "/" && path.startsWith(href))) {
            link.classList.add("active");
        }
    });

    /* -----------------------------------------------------------
       Auto-dismiss flash / toast messages after a few seconds
       ----------------------------------------------------------- */
    var flashes = document.querySelectorAll(".flash");
    flashes.forEach(function (flash, index) {
        setTimeout(function () {
            flash.style.transition = "opacity .4s ease, transform .4s ease";
            flash.style.opacity = "0";
            flash.style.transform = "translateY(-10px) scale(.96)";
            setTimeout(function () { flash.remove(); }, 400);
        }, 4500 + index * 300);
    });

    /* -----------------------------------------------------------
       Prevent double-submit on slower mobile connections:
       disable the submit button and show a lightweight loading
       state once a form is submitted.
       ----------------------------------------------------------- */
    document.querySelectorAll("form").forEach(function (form) {
        form.addEventListener("submit", function () {
            var btn = form.querySelector("button[type=submit]");
            if (btn && !btn.classList.contains("no-loading-state")) {
                btn.dataset.originalText = btn.innerHTML;
                btn.classList.add("is-loading");
                btn.innerHTML = "Please wait…";
                setTimeout(function () {
                    btn.disabled = true;
                }, 0);
            }
        });
    });

    /* -----------------------------------------------------------
       Quiz: live "answered X of Y" counter
       ----------------------------------------------------------- */
    var quizForm = document.getElementById("quiz-form");
    if (quizForm) {
        var counter = document.getElementById("quiz-progress-count");
        var groups = quizForm.querySelectorAll(".question-card");

        function updateQuizProgress() {
            var answered = 0;
            groups.forEach(function (card) {
                if (card.querySelector("input:checked")) answered += 1;
            });
            if (counter) {
                counter.textContent = answered + " of " + groups.length + " answered";
            }
        }

        quizForm.addEventListener("change", updateQuizProgress);
        updateQuizProgress();
    }

    /* -----------------------------------------------------------
       Register / settings: live password match check
       ----------------------------------------------------------- */
    function wireMatchCheck(passId, confirmId, msgId) {
        var pass = document.getElementById(passId);
        var confirm = document.getElementById(confirmId);
        var msg = document.getElementById(msgId);
        if (!pass || !confirm || !msg) return;

        function check() {
            if (!confirm.value) { msg.textContent = ""; return; }
            if (pass.value === confirm.value) {
                msg.textContent = "Passwords match";
                msg.style.color = "var(--success)";
            } else {
                msg.textContent = "Passwords do not match";
                msg.style.color = "var(--danger)";
            }
        }
        pass.addEventListener("input", check);
        confirm.addEventListener("input", check);
    }

    wireMatchCheck("register-password", "register-confirm", "register-match-msg");
    wireMatchCheck("new-password", "confirm-password", "settings-match-msg");

    /* -----------------------------------------------------------
       File inputs: show the chosen filename
       ----------------------------------------------------------- */
    document.querySelectorAll("input[type=file]").forEach(function (input) {
        var label = document.querySelector('[data-file-label-for="' + input.id + '"]');
        if (!label) return;
        var defaultText = label.textContent;
        input.addEventListener("change", function () {
            label.textContent = input.files.length ? input.files[0].name : defaultText;
        });
    });

    /* -----------------------------------------------------------
       Admin: toggle material link/upload fields
       ----------------------------------------------------------- */
    var materialTypeInputs = document.querySelectorAll("input[name=material_type]");
    if (materialTypeInputs.length) {
        var linkField = document.getElementById("material-link-field");
        var fileField = document.getElementById("material-file-field");

        function toggleMaterialFields() {
            var selected = document.querySelector("input[name=material_type]:checked");
            if (!selected) return;
            if (selected.value === "pdf") {
                linkField.style.display = "none";
                fileField.style.display = "block";
            } else {
                linkField.style.display = "block";
                fileField.style.display = "none";
            }
        }

        materialTypeInputs.forEach(function (input) {
            input.addEventListener("change", toggleMaterialFields);
        });
        toggleMaterialFields();
    }

    /* -----------------------------------------------------------
       Theme toggle (dark / light)
       Pre-paint snippet in <head> already set data-theme; this
       just wires the button, persists the choice, and keeps any
       open Chart.js instances in sync.
       ----------------------------------------------------------- */
    var root = document.documentElement;

    function setToggleIcon(theme) {
        document.querySelectorAll("[data-theme-toggle] i").forEach(function (icon) {
            icon.className = theme === "dark" ? "bi bi-sun-fill" : "bi bi-moon-stars-fill";
        });
        var meta = document.querySelector('meta[name="theme-color"]');
        if (meta) meta.setAttribute("content", theme === "dark" ? "#0A0E17" : "#2563eb");
    }
    setToggleIcon(root.getAttribute("data-theme") || "light");

    document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
            root.setAttribute("data-theme", next);
            try { localStorage.setItem("lh-theme", next); } catch (e) {}
            setToggleIcon(next);
            document.dispatchEvent(new CustomEvent("lh:themechange", { detail: { theme: next } }));
        });
    });

    /* -----------------------------------------------------------
       Animated number counters (stat cards, score boxes)
       Triggers once when the element scrolls into view.
       ----------------------------------------------------------- */
    var counterTargets = document.querySelectorAll("[data-count-to]");
    if (counterTargets.length && "IntersectionObserver" in window) {
        var counterObserver = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) return;
                animateCounter(entry.target);
                counterObserver.unobserve(entry.target);
            });
        }, { threshold: 0.4 });
        counterTargets.forEach(function (el) { counterObserver.observe(el); });
    } else {
        counterTargets.forEach(animateCounter);
    }

    function animateCounter(el) {
        var target = parseFloat(el.dataset.countTo);
        var suffix = el.dataset.countSuffix || "";
        var decimals = el.dataset.countDecimals ? parseInt(el.dataset.countDecimals, 10) : 0;
        var duration = 900;
        var start = performance.now();

        function tick(now) {
            var progress = Math.min((now - start) / duration, 1);
            var eased = 1 - Math.pow(1 - progress, 3);
            var value = target * eased;
            el.textContent = value.toFixed(decimals) + suffix;
            if (progress < 1) requestAnimationFrame(tick);
            else el.textContent = target.toFixed(decimals) + suffix;
        }
        requestAnimationFrame(tick);
    }

    /* -----------------------------------------------------------
       Animate progress rings / bars in from zero on load
       (values already server-rendered into CSS vars / width;
       we just replay the transition for a premium feel)
       ----------------------------------------------------------- */
    document.querySelectorAll(".progress-ring[style*='--progress']").forEach(function (ring) {
        var match = ring.getAttribute("style").match(/--progress:\s*([\d.]+)/);
        if (!match) return;
        var target = match[1];
        ring.style.setProperty("--progress", 0);
        requestAnimationFrame(function () {
            setTimeout(function () { ring.style.setProperty("--progress", target); }, 60);
        });
    });

    document.querySelectorAll(".bar-fill").forEach(function (bar) {
        var target = bar.style.width || "0%";
        bar.style.width = "0%";
        requestAnimationFrame(function () {
            setTimeout(function () { bar.style.width = target; }, 60);
        });
    });

    /* -----------------------------------------------------------
       Profile / avatar images: fade in once loaded, skeleton
       shimmer shows until then.
       ----------------------------------------------------------- */
    document.querySelectorAll("img[data-fade-in]").forEach(function (img) {
        if (img.complete) {
            img.classList.add("loaded");
        } else {
            img.addEventListener("load", function () { img.classList.add("loaded"); });
        }
    });

    /* -----------------------------------------------------------
       Glass confirm modal — replaces window.confirm() on forms
       marked with data-confirm-title / data-confirm-message.
       ----------------------------------------------------------- */
    var overlay = document.getElementById("confirm-modal-overlay");
    if (overlay) {
        var titleEl = overlay.querySelector("[data-modal-title]");
        var msgEl = overlay.querySelector("[data-modal-message]");
        var confirmBtn = overlay.querySelector("[data-modal-confirm]");
        var cancelBtn = overlay.querySelector("[data-modal-cancel]");
        var pendingForm = null;

        function openModal(form) {
            pendingForm = form;
            titleEl.textContent = form.dataset.confirmTitle || "Are you sure?";
            msgEl.textContent = form.dataset.confirmMessage || "This action cannot be undone.";
            overlay.classList.add("is-open");
        }
        function closeModal() {
            overlay.classList.remove("is-open");
            pendingForm = null;
        }

        document.querySelectorAll("form[data-confirm-title], form[data-confirm-message]").forEach(function (form) {
            form.addEventListener("submit", function (e) {
                if (form.dataset.confirmed === "true") return;
                e.preventDefault();
                openModal(form);
            });
        });

        confirmBtn.addEventListener("click", function () {
            if (!pendingForm) return;
            pendingForm.dataset.confirmed = "true";
            var formToSubmit = pendingForm;
            closeModal();
            formToSubmit.requestSubmit ? formToSubmit.requestSubmit() : formToSubmit.submit();
        });
        cancelBtn.addEventListener("click", closeModal);
        overlay.addEventListener("click", function (e) {
            if (e.target === overlay) closeModal();
        });
        document.addEventListener("keydown", function (e) {
            if (e.key === "Escape" && overlay.classList.contains("is-open")) closeModal();
        });
    }
});

/* =============================================================
   Chart.js helpers — called from page-level <script> blocks
   that already have the Jinja-rendered data available. Colors
   are read from the live CSS custom properties so charts match
   the current theme and re-tint instantly on toggle.
   ============================================================= */
LH.chartColors = function () {
    var css = getComputedStyle(document.documentElement);
    return {
        primary: css.getPropertyValue("--primary").trim(),
        violet: css.getPropertyValue("--violet").trim(),
        accent: css.getPropertyValue("--accent").trim(),
        ink: css.getPropertyValue("--ink").trim(),
        muted: css.getPropertyValue("--muted").trim(),
        border: css.getPropertyValue("--border-color").trim(),
        surface: css.getPropertyValue("--surface").trim()
    };
};

LH.charts = [];

LH.registerChart = function (chart) {
    LH.charts.push(chart);
    return chart;
};

document.addEventListener("lh:themechange", function () {
    if (typeof Chart === "undefined") return;
    var c = LH.chartColors();
    LH.charts.forEach(function (chart) {
        if (chart.options.scales) {
            Object.keys(chart.options.scales).forEach(function (axis) {
                var scale = chart.options.scales[axis];
                if (scale.ticks) scale.ticks.color = c.muted;
                if (scale.grid) scale.grid.color = c.border;
            });
        }
        if (chart.options.plugins && chart.options.plugins.legend) {
            chart.options.plugins.legend.labels.color = c.ink;
        }
        chart.update();
    });
});
