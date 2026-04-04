/**
 * PlantPriceTracker — Improve Page
 *
 * Handles:
 *   1. Form: char counter, validation, ?submitted=1 thank-you state
 *   2. Upvoting: localStorage-persisted, optimistic UI, per-item count
 *   3. Feed filtering: filter tabs by status, sort by upvotes / newest / responded
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'ppt_upvotes';   // Set of fb-XXX IDs the user has upvoted

    /* -----------------------------------------------------------------------
       Upvote storage
    ----------------------------------------------------------------------- */
    function loadUpvoted() {
        try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'); }
        catch (e) { return []; }
    }

    function saveUpvoted(arr) {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(arr)); }
        catch (e) {}
    }

    function hasUpvoted(id) {
        return loadUpvoted().indexOf(id) !== -1;
    }

    function addUpvote(id) {
        var arr = loadUpvoted();
        if (arr.indexOf(id) === -1) arr.push(id);
        saveUpvoted(arr);
    }

    function removeUpvote(id) {
        var arr = loadUpvoted().filter(function (x) { return x !== id; });
        saveUpvoted(arr);
    }

    /* -----------------------------------------------------------------------
       Upvote buttons — mark already-upvoted on load, wire click handlers
    ----------------------------------------------------------------------- */
    function initUpvotes() {
        var buttons = document.querySelectorAll('.upvote-btn');
        buttons.forEach(function (btn) {
            var id = btn.getAttribute('data-id');
            var countEl = document.getElementById('count-' + id);

            // Restore upvoted state from localStorage
            if (hasUpvoted(id)) {
                btn.classList.add('upvoted');
                btn.setAttribute('aria-pressed', 'true');
            }

            btn.addEventListener('click', function () {
                var already = hasUpvoted(id);
                var current = parseInt(countEl.textContent, 10) || 0;

                if (already) {
                    // Toggle off
                    removeUpvote(id);
                    countEl.textContent = current - 1;
                    btn.classList.remove('upvoted');
                    btn.setAttribute('aria-pressed', 'false');
                } else {
                    // Toggle on
                    addUpvote(id);
                    countEl.textContent = current + 1;
                    btn.classList.add('upvoted');
                    btn.setAttribute('aria-pressed', 'true');

                    // Brief bounce animation
                    btn.style.transform = 'scale(1.15)';
                    setTimeout(function () { btn.style.transform = ''; }, 160);
                }

                // Re-sort if sorted by upvotes
                var sortEl = document.getElementById('feed-sort');
                if (sortEl && sortEl.value === 'upvotes') applySort('upvotes');
            });
        });
    }

    /* -----------------------------------------------------------------------
       Filter tabs
    ----------------------------------------------------------------------- */
    function initFilters() {
        var tabs = document.querySelectorAll('.feed-filter');
        var cards = document.querySelectorAll('.feedback-card');

        tabs.forEach(function (tab) {
            tab.addEventListener('click', function () {
                tabs.forEach(function (t) {
                    t.classList.remove('active');
                    t.setAttribute('aria-selected', 'false');
                });
                tab.classList.add('active');
                tab.setAttribute('aria-selected', 'true');

                var filter = tab.getAttribute('data-filter');
                cards.forEach(function (card) {
                    var status = card.getAttribute('data-status');
                    var show = filter === 'all' || status === filter;
                    card.classList.toggle('hidden', !show);
                });
            });
        });
    }

    /* -----------------------------------------------------------------------
       Sort
    ----------------------------------------------------------------------- */
    function applySort(mode) {
        var feed = document.getElementById('feedback-feed');
        if (!feed) return;

        var cards = Array.prototype.slice.call(feed.querySelectorAll('.feedback-card'));

        cards.sort(function (a, b) {
            if (mode === 'upvotes') {
                var ua = parseInt(a.getAttribute('data-upvotes'), 10) || 0;
                var ub = parseInt(b.getAttribute('data-upvotes'), 10) || 0;
                return ub - ua;
            }
            if (mode === 'newest') {
                var da = a.getAttribute('data-submitted') || '';
                var db = b.getAttribute('data-submitted') || '';
                return db.localeCompare(da);
            }
            if (mode === 'responded') {
                // Cards with a .feedback-response block first
                var ra = a.querySelector('.feedback-response') ? 0 : 1;
                var rb = b.querySelector('.feedback-response') ? 0 : 1;
                if (ra !== rb) return ra - rb;
                // Then by newest
                var sa = a.getAttribute('data-submitted') || '';
                var sb = b.getAttribute('data-submitted') || '';
                return sb.localeCompare(sa);
            }
            return 0;
        });

        cards.forEach(function (card) { feed.appendChild(card); });
    }

    function initSort() {
        var select = document.getElementById('feed-sort');
        if (!select) return;
        select.addEventListener('change', function () { applySort(this.value); });
        applySort(select.value);   // Apply default on load
    }

    /* -----------------------------------------------------------------------
       Character counter for the body textarea
    ----------------------------------------------------------------------- */
    function initCharCount() {
        var textarea = document.getElementById('fb-body');
        var counter  = document.getElementById('body-count');
        if (!textarea || !counter) return;

        function update() {
            var len = textarea.value.length;
            var max = parseInt(textarea.getAttribute('maxlength'), 10) || 1000;
            counter.textContent = len + ' / ' + max;
            counter.classList.toggle('near-limit', len > max * 0.85);
        }
        textarea.addEventListener('input', update);
        update();
    }

    /* -----------------------------------------------------------------------
       Form: ?submitted=1 thank-you state
    ----------------------------------------------------------------------- */
    function initFormState() {
        var form   = document.getElementById('improve-form');
        var thanks = document.getElementById('form-thanks');
        if (!form || !thanks) return;

        var params = new URLSearchParams(window.location.search);
        if (params.get('submitted') === '1') {
            form.style.display = 'none';
            thanks.style.display = 'block';
        }
    }

    /* -----------------------------------------------------------------------
       Form: light client-side validation (don't submit empty fields)
    ----------------------------------------------------------------------- */
    function initFormValidation() {
        var form = document.getElementById('improve-form');
        var btn  = document.getElementById('submit-btn');
        if (!form || !btn) return;

        form.addEventListener('submit', function (e) {
            var category = document.getElementById('fb-category');
            var title    = document.getElementById('fb-title');
            var body     = document.getElementById('fb-body');
            var missing  = [];

            if (!category || !category.value) missing.push('Category');
            if (!title    || !title.value.trim()) missing.push('Summary');
            if (!body     || !body.value.trim())  missing.push('Details');

            if (missing.length) {
                e.preventDefault();
                alert('Please fill in: ' + missing.join(', '));
                return;
            }

            // Disable button to prevent double-submit
            btn.disabled = true;
            btn.textContent = 'Sending…';
        });
    }

    /* -----------------------------------------------------------------------
       Init
    ----------------------------------------------------------------------- */
    document.addEventListener('DOMContentLoaded', function () {
        initUpvotes();
        initFilters();
        initSort();
        initCharCount();
        initFormState();
        initFormValidation();
    });

}());
