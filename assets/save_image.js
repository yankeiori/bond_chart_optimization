document.addEventListener('click', function(e) {
    if (!e.target || !e.target.closest) return;

    // 画像保存
    var imgBtn = e.target.closest('#save-image-btn');
    if (imgBtn) {
        var el = document.getElementById('summary-table-container');
        if (!el) return;
        if (typeof html2canvas === 'undefined') {
            alert('画像保存機能を読み込み中です。少し待ってから再度お試しください。');
            return;
        }

        // スクロール制限を一時解除して全体をキャプチャ
        var tableDiv = el.querySelector('.dash-spreadsheet-container');
        var inner = el.querySelector('.dash-spreadsheet-inner');
        var savedStyles = [];
        var targets = [tableDiv, inner].filter(Boolean);
        targets.forEach(function(t) {
            savedStyles.push({
                el: t,
                maxHeight: t.style.maxHeight,
                overflowY: t.style.overflowY,
                overflow: t.style.overflow,
                height: t.style.height,
            });
            t.style.maxHeight = 'none';
            t.style.overflowY = 'visible';
            t.style.overflow = 'visible';
            t.style.height = 'auto';
        });

        html2canvas(el, {
            backgroundColor: '#ffffff',
            useCORS: true,
            scale: 2,
            scrollY: -window.scrollY,
            windowHeight: el.scrollHeight,
        }).then(function(canvas) {
            var link = document.createElement('a');
            link.download = 'bond_chart.png';
            link.href = canvas.toDataURL('image/png');
            link.click();
        }).finally(function() {
            // スタイルを復元
            savedStyles.forEach(function(s) {
                s.el.style.maxHeight = s.maxHeight;
                s.el.style.overflowY = s.overflowY;
                s.el.style.overflow = s.overflow;
                s.el.style.height = s.height;
            });
        });
        return;
    }

    // CSV保存
    var csvBtn = e.target.closest('#save-csv-btn');
    if (csvBtn) {
        var csvJson = window._bondChartCsvData;
        if (!csvJson) return;
        var data = JSON.parse(csvJson);
        var lines = [];
        lines.push(data.header.join(','));
        for (var i = 0; i < data.rows.length; i++) {
            var row = data.rows[i].map(function(cell) {
                if (cell.indexOf(',') >= 0 || cell.indexOf('\n') >= 0 || cell.indexOf('"') >= 0) {
                    return '"' + cell.replace(/"/g, '""') + '"';
                }
                return cell;
            });
            lines.push(row.join(','));
        }
        var csvContent = '\uFEFF' + lines.join('\n');
        var blob = new Blob([csvContent], {type: 'text/csv;charset=utf-8;'});
        var link = document.createElement('a');
        link.download = 'bond_chart.csv';
        link.href = URL.createObjectURL(blob);
        link.click();
        URL.revokeObjectURL(link.href);
        return;
    }

    // グラフ（経験値 vs 絆ボーナス）の画像保存
    var graphImgBtn = e.target.closest('#save-graph-image-btn');
    if (graphImgBtn) {
        var graph = document.getElementById('bond-graph');
        if (!graph) return;
        if (typeof html2canvas === 'undefined') {
            alert('画像保存機能を読み込み中です。少し待ってから再度お試しください。');
            return;
        }
        html2canvas(graph, {
            backgroundColor: '#ffffff',
            scale: 2,
            scrollY: -window.scrollY,
        }).then(function(canvas) {
            var link = document.createElement('a');
            link.download = 'bond_bonus_graph.png';
            link.href = canvas.toDataURL('image/png');
            link.click();
        });
        return;
    }

    // 詳細チャート画像保存
    var detailImgBtn = e.target.closest('#save-detail-image-btn');
    if (detailImgBtn) {
        var el = document.getElementById('detail-table-container');
        if (!el) return;
        if (typeof html2canvas === 'undefined') {
            alert('画像保存機能を読み込み中です。少し待ってから再度お試しください。');
            return;
        }

        var tableDiv = el.querySelector('.dash-spreadsheet-container');
        var inner = el.querySelector('.dash-spreadsheet-inner');
        var savedStyles = [];
        var targets = [tableDiv, inner].filter(Boolean);
        targets.forEach(function(t) {
            savedStyles.push({
                el: t,
                maxHeight: t.style.maxHeight,
                overflowY: t.style.overflowY,
                overflow: t.style.overflow,
                height: t.style.height,
            });
            t.style.maxHeight = 'none';
            t.style.overflowY = 'visible';
            t.style.overflow = 'visible';
            t.style.height = 'auto';
        });

        html2canvas(el, {
            backgroundColor: '#ffffff',
            useCORS: true,
            scale: 2,
            scrollY: -window.scrollY,
            windowHeight: el.scrollHeight,
        }).then(function(canvas) {
            var link = document.createElement('a');
            link.download = 'bond_detail_chart.png';
            link.href = canvas.toDataURL('image/png');
            link.click();
        }).finally(function() {
            savedStyles.forEach(function(s) {
                s.el.style.maxHeight = s.maxHeight;
                s.el.style.overflowY = s.overflowY;
                s.el.style.overflow = s.overflow;
                s.el.style.height = s.height;
            });
        });
        return;
    }

    // 詳細チャートCSV保存
    var detailCsvBtn = e.target.closest('#save-detail-csv-btn');
    if (detailCsvBtn) {
        var csvJson = window._bondDetailCsvData;
        if (!csvJson) return;
        var data = JSON.parse(csvJson);
        var lines = [];
        lines.push(data.header.join(','));
        for (var i = 0; i < data.rows.length; i++) {
            var row = data.rows[i].map(function(cell) {
                if (cell.indexOf(',') >= 0 || cell.indexOf('\n') >= 0 || cell.indexOf('"') >= 0) {
                    return '"' + cell.replace(/"/g, '""') + '"';
                }
                return cell;
            });
            lines.push(row.join(','));
        }
        var csvContent = '\uFEFF' + lines.join('\n');
        var blob = new Blob([csvContent], {type: 'text/csv;charset=utf-8;'});
        var link = document.createElement('a');
        link.download = 'bond_detail_chart.csv';
        link.href = URL.createObjectURL(blob);
        link.click();
        URL.revokeObjectURL(link.href);
        return;
    }
});
