function initializeGrid(pageName, savedLayout, defaultLayout) {
    const grid = GridStack.init({
        minW: 2,
        minH: 2
    });
    window.grid = grid; // Make it global for other scripts to access

    if (savedLayout) {
        grid.load(savedLayout, true);
    } else if (defaultLayout) {
        grid.load(defaultLayout, true);
    }

    const saveGridState = () => {
        const layout = grid.save(false);
        fetch(`/save_layout/${pageName}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ layout: layout }),
        });
    };

    grid.on('change', saveGridState);
    grid.on('added', saveGridState);
    grid.on('removed', saveGridState);

    const restoreBtn = document.getElementById('restore-layout-btn');
    if (restoreBtn) {
        restoreBtn.addEventListener('click', function() {
            if (confirm('Are you sure you want to restore the default layout? This will discard your current customizations.')) {
                fetch(`/delete_layout/${pageName}`, {
                    method: 'POST'
                }).then(response => {
                    if (response.ok) {
                        window.location.reload();
                    } else {
                        alert('Failed to restore default layout.');
                    }
                });
            }
        });
    }
}
