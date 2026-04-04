/**
 * PlantPriceTracker — My Plant List (Wishlist)
 * localStorage-based, no backend required.
 *
 * Storage: localStorage['ppt_wishlist'] = JSON object keyed by plant ID
 * Each entry: { id, name, botanical_name, category, price_range, zones, saved_at }
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'ppt_wishlist';

    function load() {
        try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); }
        catch (e) { return {}; }
    }

    function persist(data) {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(data)); }
        catch (e) { /* storage full — silently ignore */ }
    }

    // -------------------------------------------------------------------------
    // Public API
    // -------------------------------------------------------------------------
    window.pptWishlist = {

        add: function (id, meta) {
            var data = load();
            data[id] = {
                id: id,
                name: meta.name || id,
                botanical_name: meta.botanical_name || '',
                category: meta.category || '',
                price_range: meta.price_range || '',
                zones: meta.zones || [],
                saved_at: new Date().toISOString()
            };
            persist(data);
            _refreshButtons(id, true);
            _refreshNavCount();
        },

        remove: function (id) {
            var data = load();
            delete data[id];
            persist(data);
            _refreshButtons(id, false);
            _refreshNavCount();
        },

        toggle: function (id, meta) {
            if (this.has(id)) {
                this.remove(id);
                return false;
            } else {
                this.add(id, meta);
                return true;
            }
        },

        has: function (id) { return !!load()[id]; },

        getAll: function () { return Object.values(load()); },

        count: function () { return Object.keys(load()).length; },

        clear: function () {
            persist({});
            _refreshNavCount();
        }
    };

    // -------------------------------------------------------------------------
    // UI helpers
    // -------------------------------------------------------------------------
    function _refreshButtons(id, saved) {
        document.querySelectorAll('.wishlist-btn[data-plant-id="' + id + '"]').forEach(function (btn) {
            btn.classList.toggle('saved', saved);
            btn.innerHTML = saved
                ? '<span class="wl-heart">&#x2665;</span> Saved'
                : '<span class="wl-heart">&#x2661;</span> Save to My List';
            btn.setAttribute('aria-pressed', saved ? 'true' : 'false');
        });
    }

    function _refreshNavCount() {
        var count = pptWishlist.count();
        document.querySelectorAll('.wishlist-nav-count').forEach(function (el) {
            el.textContent = count > 0 ? ' (' + count + ')' : '';
        });
    }

    // -------------------------------------------------------------------------
    // Boot: set initial state when DOM is ready
    // -------------------------------------------------------------------------
    function _boot() {
        _refreshNavCount();

        // Initialise state for any wishlist buttons already on this page
        document.querySelectorAll('.wishlist-btn').forEach(function (btn) {
            var id = btn.getAttribute('data-plant-id');
            if (id && pptWishlist.has(id)) {
                btn.classList.add('saved');
                btn.innerHTML = '<span class="wl-heart">&#x2665;</span> Saved';
                btn.setAttribute('aria-pressed', 'true');
            }
        });

        // Wire up click handlers for wishlist buttons
        document.addEventListener('click', function (e) {
            var btn = e.target.closest('.wishlist-btn');
            if (!btn) return;
            e.preventDefault();

            var id = btn.getAttribute('data-plant-id');
            if (!id) return;

            var meta = {
                name: btn.getAttribute('data-plant-name') || '',
                botanical_name: btn.getAttribute('data-plant-botanical') || '',
                category: btn.getAttribute('data-plant-category') || '',
                price_range: btn.getAttribute('data-plant-price-range') || '',
                zones: (btn.getAttribute('data-plant-zones') || '').split(',').map(Number).filter(Boolean)
            };

            pptWishlist.toggle(id, meta);
        });

        // Wishlist page rendering
        var container = document.getElementById('wishlist-container');
        if (container) {
            _renderWishlistPage(container);
        }
    }

    // -------------------------------------------------------------------------
    // Wishlist page renderer
    // -------------------------------------------------------------------------
    function _renderWishlistPage(container) {
        var plants = pptWishlist.getAll();

        var countEl = document.getElementById('wishlist-count');
        if (countEl) countEl.textContent = plants.length;

        if (plants.length === 0) {
            container.innerHTML = _emptyState();
            return;
        }

        // Sort by most recently saved
        plants.sort(function (a, b) { return (b.saved_at || '').localeCompare(a.saved_at || ''); });

        var html = '<div class="wl-grid">';
        plants.forEach(function (p) {
            html += _plantCard(p);
        });
        html += '</div>';
        container.innerHTML = html;

        // Wire remove buttons
        container.addEventListener('click', function (e) {
            var btn = e.target.closest('.wl-remove-btn');
            if (!btn) return;
            var id = btn.getAttribute('data-plant-id');
            if (!id) return;
            pptWishlist.remove(id);
            // Remove card from DOM
            var card = container.querySelector('.wl-card[data-plant-id="' + id + '"]');
            if (card) {
                card.style.opacity = '0';
                card.style.transform = 'scale(0.95)';
                setTimeout(function () {
                    card.remove();
                    if (pptWishlist.count() === 0) {
                        container.innerHTML = _emptyState();
                    }
                    if (countEl) countEl.textContent = pptWishlist.count();
                }, 200);
            }
        });

        // Clear all button
        var clearBtn = document.getElementById('wl-clear-all');
        if (clearBtn) {
            clearBtn.addEventListener('click', function () {
                if (!confirm('Remove all plants from your list?')) return;
                pptWishlist.clear();
                container.innerHTML = _emptyState();
                if (countEl) countEl.textContent = '0';
            });
        }
    }

    function _plantCard(p) {
        var categoryLabel = (p.category || '').replace(/-/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); });
        var zonesText = p.zones && p.zones.length > 0 ? 'Zones ' + p.zones.join(', ') : '';
        var savedDate = p.saved_at ? new Date(p.saved_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '';

        return '<div class="wl-card" data-plant-id="' + _esc(p.id) + '" style="transition:opacity .2s,transform .2s;">'
            + '<div class="wl-card-body">'
            + '<a href="/plants/' + _esc(p.id) + '.html" class="wl-card-name">' + _esc(p.name) + '</a>'
            + (p.botanical_name ? '<p class="wl-card-botanical">' + _esc(p.botanical_name) + '</p>' : '')
            + '<div class="wl-card-meta">'
            + (categoryLabel ? '<span class="wl-badge">' + _esc(categoryLabel) + '</span>' : '')
            + (zonesText ? '<span class="wl-zones">' + _esc(zonesText) + '</span>' : '')
            + '</div>'
            + (p.price_range ? '<p class="wl-card-price">' + _esc(p.price_range) + '</p>' : '')
            + '</div>'
            + '<div class="wl-card-footer">'
            + (savedDate ? '<span class="wl-saved-date">Saved ' + savedDate + '</span>' : '')
            + '<button class="wl-remove-btn" data-plant-id="' + _esc(p.id) + '" title="Remove from list" aria-label="Remove ' + _esc(p.name) + ' from list">&times; Remove</button>'
            + '</div>'
            + '</div>';
    }

    function _emptyState() {
        return '<div class="wl-empty">'
            + '<p class="wl-empty-icon">&#x1F331;</p>'
            + '<h3>Your list is empty</h3>'
            + '<p>Browse plants and click <strong>&#x2661; Save to My List</strong> to track ones you\'re interested in.</p>'
            + '<a href="/" class="hero-cta">Browse Plants</a>'
            + '</div>';
    }

    function _esc(str) {
        return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    // Boot on DOMContentLoaded (or immediately if already loaded)
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _boot);
    } else {
        _boot();
    }

})();
