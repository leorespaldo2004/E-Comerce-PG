/**
 * index.js
 * Lightweight logic for the SSR-rendered Index page.
 * Principles: Progressive Enhancement, Zero-Fetch Initialization.
 */

// Cart State (Local only for now)
let CART = {};

document.addEventListener('DOMContentLoaded', () => {
    // 1. Recover Cart State
    // (In a real app, this might pull from localStorage)
    
    // 2. Setup Interactions
    setupSearch();
    updateCartUI();
});

/**
 * Handles Client-Side search filtering.
 * Since HTML is already there, we just toggle visibility.
 * FAST: No re-rendering of DOM, just CSS changes.
 */
function setupSearch() {
    const searchInput = document.getElementById('search-input');
    
    if (!searchInput) return;

    // Focus input if there's a value (User just searched)
    if (searchInput.value.trim() !== "") {
        searchInput.focus();
    }

    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault(); // Prevent default if inside a form
            const term = e.target.value.trim();
            
            if (term) {
                // Redirect to server with query param
                window.location.href = `/?q=${encodeURIComponent(term)}`;
            } else {
                // If empty, go back to home/reset
                window.location.href = '/';
            }
        }
    });
}

/**
 * Adds item to cart (Global function called by onclick in HTML)
 * @param {string} id - Product ID
 */
function addToCart(id) {
    CART[id] = (CART[id] || 0) + 1;
    updateCartUI();
    
    // Visual Feedback Animation
    const btn = document.getElementById('cart-btn-top');
    if (btn) {
        btn.classList.add('scale-110', 'text-primary');
        setTimeout(() => btn.classList.remove('scale-110', 'text-primary'), 200);
    }
}

/**
 * Updates all cart counters in the UI.
 */
function updateCartUI() {
    const totalItems = Object.values(CART).reduce((a, b) => a + b, 0);
    const badgeTop = document.getElementById('cart-count');
    const badgeBottom = document.querySelector('.cart-badge-btm');

    if (totalItems > 0) {
        if (badgeTop) {
            badgeTop.innerText = totalItems;
            badgeTop.classList.remove('hidden');
            badgeTop.classList.add('flex');
        }
        if (badgeBottom) badgeBottom.classList.remove('hidden');
    } else {
        if (badgeTop) badgeTop.classList.add('hidden');
        if (badgeBottom) badgeBottom.classList.add('hidden');
    }
}