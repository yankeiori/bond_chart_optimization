/**
 * クライアントサイド Sidney 分解ソルバー
 *
 * Python の chart_solver.py (solve_sidney) を JavaScript に移植したもの。
 * Dash の clientside_callback として登録される。
 */

/* ------------------------------------------------------------------ */
/*  定数                                                               */
/* ------------------------------------------------------------------ */

var _solver_BOND_EXP_PER_LEVEL = [
    15, 30, 30, 35, 35, 35, 40, 40, 40,
    60, 90, 105, 120, 140, 160, 180, 205, 230, 255,
    285, 315, 345, 375, 410, 445, 480, 520, 560, 600,
    645, 690, 735, 780, 830, 880, 930, 985, 1040, 1095,
    1155, 1215, 1275, 1335, 1400, 1465, 1530, 1600, 1670, 1740,
];

var _solver_BOND_RANGES = [
    [2, 5], [6, 10], [11, 15], [16, 20],
    [21, 30], [31, 40], [41, 50],
];

/* ------------------------------------------------------------------ */
/*  ユーティリティ                                                      */
/* ------------------------------------------------------------------ */

function _solver_arraysEqual(a, b) {
    if (a.length !== b.length) return false;
    for (var i = 0; i < a.length; i++) {
        if (a[i] !== b[i]) return false;
    }
    return true;
}

function _solver_defaultCostumeName(index) {
    return "\u8863\u88c5" + (index + 1);
}

/* ------------------------------------------------------------------ */
/*  累積ボーナス                                                        */
/* ------------------------------------------------------------------ */

function _solver_cumulativeBonus(bondBonuses) {
    var cum = new Array(51);
    cum[0] = 0;
    cum[1] = 0;
    for (var lv = 2; lv <= 50; lv++) {
        var bonus = 0;
        for (var idx = 0; idx < _solver_BOND_RANGES.length; idx++) {
            if (lv >= _solver_BOND_RANGES[idx][0] && lv <= _solver_BOND_RANGES[idx][1]) {
                bonus = bondBonuses[idx];
                break;
            }
        }
        cum[lv] = cum[lv - 1] + bonus;
    }
    return cum;
}

/* ------------------------------------------------------------------ */
/*  Sidney 分解ソルバー                                                 */
/* ------------------------------------------------------------------ */

/**
 * Sidney 分解により最適な絆上げ順序を O(T log T) で計算する。
 *
 * @param {number[]} currentRanks - 各衣装の現在ランク
 * @param {number[][]} allBondBonuses - 各衣装の bond_bonuses (長さ7)
 * @param {Object} priorityMap - ソルバー内index → 優先度 (小さいほど優先)
 * @param {number} bond50Penalty - 絆50到達ペナルティ (0~1)
 * @returns {{ path: number[][], totalScore: number, cumPerCostume: number[][] }}
 */
function _solver_solveSidney(currentRanks, allBondBonuses, priorityMap, bond50Penalty) {
    var n = currentRanks.length;
    var cumPerCostume = allBondBonuses.map(function (bb) {
        return _solver_cumulativeBonus(bb);
    });

    // 絆50ペナルティ: 全衣装の絆50ボーナスの最大値から減算量を決定
    var penalty50 = 0;
    if (bond50Penalty > 0) {
        var maxP50 = 0;
        for (var pi = 0; pi < n; pi++) {
            var p50 = cumPerCostume[pi][50] - cumPerCostume[pi][49];
            if (p50 > maxP50) maxP50 = p50;
        }
        penalty50 = Math.round(maxP50 * bond50Penalty);
    }

    // 各衣装のジョブチェーンを構築し Sidney 分解
    // ブロック: { p: number, w: number, jobs: {ci, r}[] }
    var allBlocks = [];

    for (var ci = 0; ci < n; ci++) {
        var stack = []; // { p, w, jobs }
        for (var r = currentRanks[ci]; r < 50; r++) {
            var w = _solver_BOND_EXP_PER_LEVEL[r - 1];
            var p = cumPerCostume[ci][r + 1] - cumPerCostume[ci][r];
            // 絆50ペナルティ: ランク49→50のジョブに一律減算（負にならない）
            if (r === 49 && penalty50 > 0) {
                p = Math.max(0, p - penalty50);
            }
            var newBlock = { p: p, w: w, jobs: [{ ci: ci, r: r }] };

            // top の p/w <= new の p/w ならマージ (等価も含めて同衣装を連続させる)
            while (stack.length > 0) {
                var top = stack[stack.length - 1];
                if (top.p * newBlock.w <= newBlock.p * top.w) {
                    stack.pop();
                    newBlock = {
                        p: top.p + newBlock.p,
                        w: top.w + newBlock.w,
                        jobs: top.jobs.concat(newBlock.jobs),
                    };
                } else {
                    break;
                }
            }
            stack.push(newBlock);
        }
        for (var si = 0; si < stack.length; si++) {
            allBlocks.push(stack[si]);
        }
    }

    // ブロックを p/w 比の降順でソート (整数比較)
    allBlocks.sort(function (a, b) {
        var lhs = a.p * b.w;
        var rhs = b.p * a.w;
        if (lhs > rhs) return -1;
        if (lhs < rhs) return 1;
        // タイブレーク: 衣装優先度順
        var aPri = priorityMap[a.jobs[0].ci];
        var bPri = priorityMap[b.jobs[0].ci];
        if (aPri !== undefined && bPri !== undefined && aPri !== bPri) {
            return aPri - bPri;
        }
        return 0;
    });

    // スケジュールに従って経路とスコアを構築
    var state = currentRanks.slice();
    var path = [state.slice()];
    var totalScore = 0;
    var currentBonus = 0;
    for (var i = 0; i < n; i++) {
        currentBonus += cumPerCostume[i][state[i]];
    }

    for (var bi = 0; bi < allBlocks.length; bi++) {
        var jobs = allBlocks[bi].jobs;
        for (var ji = 0; ji < jobs.length; ji++) {
            var job = jobs[ji];
            var exp = _solver_BOND_EXP_PER_LEVEL[job.r - 1];
            // スコア計算には実際のボーナス値を使用（ペナルティの影響を受けない）
            var delta = cumPerCostume[job.ci][job.r + 1] - cumPerCostume[job.ci][job.r];
            totalScore += exp * currentBonus;
            state[job.ci] = job.r + 1;
            currentBonus += delta;
            path.push(state.slice());
        }
    }

    return { path: path, totalScore: totalScore, cumPerCostume: cumPerCostume };
}

/* ------------------------------------------------------------------ */
/*  経路要約                                                           */
/* ------------------------------------------------------------------ */

function _solver_summarizePath(path, costumeNames) {
    if (path.length <= 1) return [];

    // 各ステップでどの衣装が変わったか
    var changes = [];
    for (var i = 1; i < path.length; i++) {
        for (var c = 0; c < path[0].length; c++) {
            if (path[i][c] !== path[i - 1][c]) {
                changes.push(c);
                break;
            }
        }
    }

    // パターン検出・グループ化
    var groups = [];
    var ci = 0;
    while (ci < changes.length) {
        var bestPattern = [changes[ci]];
        var bestEnd = ci + 1;

        for (
            var patLen = 1;
            patLen <= Math.min(3, changes.length - ci);
            patLen++
        ) {
            var pattern = changes.slice(ci, ci + patLen);
            var j = ci + patLen;
            while (
                j + patLen <= changes.length &&
                _solver_arraysEqual(changes.slice(j, j + patLen), pattern)
            ) {
                j += patLen;
            }
            var remaining = changes.slice(
                j,
                Math.min(j + patLen, changes.length)
            );
            if (
                remaining.length > 0 &&
                _solver_arraysEqual(remaining, pattern.slice(0, remaining.length))
            ) {
                j += remaining.length;
            }
            if (j - ci > bestEnd - ci) {
                bestPattern = pattern.slice();
                bestEnd = j;
            }
        }

        if (bestPattern.length > 1 && bestEnd - ci <= bestPattern.length) {
            for (var k = ci; k < bestEnd; k++) {
                if (
                    groups.length > 0 &&
                    _solver_arraysEqual(groups[groups.length - 1][0], [changes[k]])
                ) {
                    var prev = groups[groups.length - 1];
                    groups[groups.length - 1] = [prev[0], prev[1], k + 1];
                } else {
                    groups.push([[changes[k]], k, k + 1]);
                }
            }
        } else {
            groups.push([bestPattern, ci, bestEnd]);
        }
        ci = bestEnd;
    }

    // 隣接する同一衣装の単一パターンをマージ
    var merged = [];
    for (var gi = 0; gi < groups.length; gi++) {
        var g = groups[gi];
        if (
            merged.length > 0 &&
            g[0].length === 1 &&
            merged[merged.length - 1][0].length === 1 &&
            g[0][0] === merged[merged.length - 1][0][0]
        ) {
            var mp = merged[merged.length - 1];
            merged[merged.length - 1] = [mp[0], mp[1], g[2]];
        } else {
            merged.push(g);
        }
    }

    // 要約行を生成
    var summary = [];
    for (var mi = 0; mi < merged.length; mi++) {
        var pat = merged[mi][0];
        var start = merged[mi][1];
        var end = merged[mi][2];
        var fromState = path[start];
        var toState = path[end];
        var desc;

        if (pat.length === 1) {
            var cc = pat[0];
            var name = costumeNames[cc];
            if (toState[cc] - fromState[cc] === 1) {
                desc = name + ": " + toState[cc];
            } else {
                desc = name + ": " + fromState[cc] + " \u2192 " + toState[cc];
            }
        } else {
            var names = pat.map(function (c) {
                return costumeNames[c];
            });
            var rotating = names.join("\u2192");
            var totalSteps = end - start;
            var fullRepeats = Math.floor(totalSteps / pat.length);
            var remainder = totalSteps % pat.length;
            var countStr = remainder === 0
                ? "x " + fullRepeats
                : "x " + fullRepeats + "+" + remainder;
            var parts = [];
            var seen = {};
            for (var pi = 0; pi < pat.length; pi++) {
                var pc = pat[pi];
                if (seen[pc]) continue;
                seen[pc] = true;
                if (fromState[pc] !== toState[pc]) {
                    if (toState[pc] - fromState[pc] === 1) {
                        parts.push(costumeNames[pc] + " " + toState[pc]);
                    } else {
                        parts.push(
                            costumeNames[pc] +
                                " " +
                                fromState[pc] +
                                " \u2192 " +
                                toState[pc]
                        );
                    }
                }
            }
            desc = "[" + rotating + "] " + countStr + " " + parts.join(", ");
        }

        summary.push({ description: desc, from: fromState, to: toState, start: start, end: end });
    }

    return summary;
}

/* ------------------------------------------------------------------ */
/*  Dash コンポーネント生成ヘルパー                                      */
/* ------------------------------------------------------------------ */

function _solver_h(type, props) {
    return {
        namespace: "dash_html_components",
        type: type,
        props: props || {},
    };
}

function _solver_dataTable(props) {
    return { namespace: "dash_table", type: "DataTable", props: props };
}

/* ------------------------------------------------------------------ */
/*  スピナーコンポーネント                                                */
/* ------------------------------------------------------------------ */

function _solver_spinnerComponent() {
    return _solver_h("Div", {
        children: _solver_h("Div", {
            style: {
                width: "40px",
                height: "40px",
                border: "4px solid #e0e0e0",
                borderTopColor: "#4a90d9",
                borderRadius: "50%",
                animation: "solver-spin .8s linear infinite",
            },
        }),
        style: {
            display: "flex",
            justifyContent: "center",
            padding: "40px",
        },
    });
}

/* ------------------------------------------------------------------ */
/*  メイン計算ロジック                                                   */
/* ------------------------------------------------------------------ */

function _solver_calcChartSync(
    rankValues, rankIds, bondValues, bondIds, costumeValues, costumeIds,
    costumePriorityOrder, bond50Penalty, costumeIcons
) {
    // --- データ組み立て ---
    var idxOrder = costumeIds.map(function (id) {
        return id.index;
    });

    var costumeNames = costumeValues.map(function (v, i) {
        return v || _solver_defaultCostumeName(costumeIds[i].index);
    });

    // 列見出しの生徒画像（プリセットから読み込んだ衣装のみ）
    var headerIconCss = [];
    costumeIds.forEach(function (id, i) {
        var src = (costumeIcons || {})[id.index];
        if (!src) return;
        headerIconCss.push({
            selector: 'th.dash-header[data-dash-column="c' + i + '"]',
            rule:
                'background-image: url("' + src + '") !important;' +
                " background-repeat: no-repeat !important;" +
                " background-position: center 4px !important;" +
                " background-size: 32px auto !important;" +
                " padding-top: 42px !important;",
        });
    });

    var rankMap = {};
    // 絆ボーナスは 50 までなので、51 以上は 50 として扱う
    rankIds.forEach(function (id, i) {
        rankMap[id.index] = Math.min(50, rankValues[i]);
    });
    var currentRanks = idxOrder.map(function (idx) {
        return rankMap[idx];
    });

    var bondMap = {};
    idxOrder.forEach(function (idx) {
        bondMap[idx] = new Array(_solver_BOND_RANGES.length).fill(0);
    });
    bondIds.forEach(function (id, i) {
        bondMap[id.index][id.range_idx] = bondValues[i] || 0;
    });
    var allBondBonuses = idxOrder.map(function (idx) {
        return bondMap[idx];
    });

    // --- 衣装優先度マップ構築 (衣装元index → ソルバー内index) ---
    var priorityMap = {};
    if (costumePriorityOrder) {
        for (var pi = 0; pi < costumePriorityOrder.length; pi++) {
            var origIdx = costumePriorityOrder[pi];
            var solverIdx = idxOrder.indexOf(origIdx);
            if (solverIdx !== -1) {
                priorityMap[solverIdx] = pi;
            }
        }
    }

    // --- Sidney 分解ソルバー実行 ---
    var result = _solver_solveSidney(
        currentRanks, allBondBonuses, priorityMap, bond50Penalty || 0
    );
    var path = result.path;
    var cumPerCostume = result.cumPerCostume;

    if (!path || path.length === 0) {
        return _solver_h("P", {
            children: "\u7d4c\u8def\u304c\u898b\u3064\u304b\u308a\u307e\u305b\u3093\u3067\u3057\u305f\u3002",
            style: { color: "red" },
        });
    }

    // --- 要約 ---
    var summary = _solver_summarizePath(path, costumeNames);

    // --- 要約表 ---
    var summaryColumns = costumeNames.map(function (name, i) {
        return { name: name, id: "c" + i };
    });
    summaryColumns.push({
        name: "\u7d46\u4e0a\u3052\u512a\u5148\u5ea6",
        id: "description",
    });
    summaryColumns.push({
        name: "#",
        id: "row_idx",
    });

    var summaryData = summary.map(function (s, idx) {
        var row = { description: s.description, row_idx: idx + 1 };
        for (var ci = 0; ci < costumeNames.length; ci++) {
            row["c" + ci] = s.to[ci];
        }
        return row;
    });

    var summaryStyleCond = [
        { if: { row_index: "odd" }, backgroundColor: "#f9f9f9" },
    ];
    // 最初の行: 初期状態 (from) との比較
    for (var ci = 0; ci < costumeNames.length; ci++) {
        if (summary.length > 0 && summary[0].to[ci] !== summary[0].from[ci]) {
            summaryStyleCond.push({
                if: { row_index: 0, column_id: "c" + ci },
                backgroundColor: "#fff3cd",
                fontWeight: "bold",
            });
        }
    }
    for (var ri = 1; ri < summary.length; ri++) {
        for (var ci = 0; ci < costumeNames.length; ci++) {
            if (summary[ri].to[ci] !== summary[ri - 1].to[ci]) {
                summaryStyleCond.push({
                    if: { row_index: ri, column_id: "c" + ci },
                    backgroundColor: "#fff3cd",
                    fontWeight: "bold",
                });
            }
        }
    }

    var summaryTable = _solver_dataTable({
        columns: summaryColumns,
        data: summaryData,
        fixed_rows: { headers: true },
        style_table: {
            overflowX: "auto",
            maxHeight: "70vh",
            overflowY: "auto",
        },
        style_cell: {
            textAlign: "center",
            padding: "4px 8px",
            fontSize: "0.9rem",
            minWidth: "60px",
            whiteSpace: "nowrap",
            overflow: "visible",
        },
        style_cell_conditional: [
            {
                if: { column_id: "description" },
                textAlign: "left",
                minWidth: "180px",
            },
            {
                if: { column_id: "row_idx" },
                minWidth: "30px",
                maxWidth: "40px",
                color: "#888",
            },
        ],
        style_header: {
            fontWeight: "bold",
            background: "#2ecc71",
            color: "white",
            position: "sticky",
            top: 0,
        },
        style_data_conditional: summaryStyleCond,
        css: headerIconCss,
        page_size: 200,
    });

    // --- 詳細表 ---
    var detailColumns = costumeNames.map(function (name, i) {
        return { name: name, id: "c" + i };
    });
    var detailData = path.map(function (step) {
        var row = {};
        for (var i = 0; i < costumeNames.length; i++) {
            row["c" + i] = step[i];
        }
        return row;
    });

    var detailStyleCond = [
        { if: { row_index: "odd" }, backgroundColor: "#f9f9f9" },
    ];
    for (var dri = 1; dri < path.length; dri++) {
        for (var dci = 0; dci < costumeNames.length; dci++) {
            if (path[dri][dci] !== path[dri - 1][dci]) {
                detailStyleCond.push({
                    if: { row_index: dri, column_id: "c" + dci },
                    backgroundColor: "#fff3cd",
                    fontWeight: "bold",
                });
            }
        }
    }

    var detailTable = _solver_dataTable({
        columns: detailColumns,
        data: detailData,
        fixed_rows: { headers: true },
        style_table: {
            overflowX: "auto",
            maxHeight: "50vh",
            overflowY: "auto",
        },
        style_cell: {
            textAlign: "center",
            padding: "4px 8px",
            fontSize: "0.9rem",
        },
        style_header: {
            fontWeight: "bold",
            background: "#2ecc71",
            color: "white",
            position: "sticky",
            top: 0,
        },
        style_data_conditional: detailStyleCond,
        css: headerIconCss,
        page_size: 200,
    });

    // --- CSV 用データをグローバルに保持 ---
    var csvHeader = costumeNames.slice();
    csvHeader.push("\u7d46\u4e0a\u3052\u512a\u5148\u5ea6");
    var csvRows = summary.map(function (s) {
        var row = costumeNames.map(function (_, ci) {
            return String(s.to[ci]);
        });
        row.push(s.description);
        return row;
    });
    window._bondChartCsvData = JSON.stringify({
        header: csvHeader,
        rows: csvRows,
    });

    // --- 詳細チャート CSV 用データ ---
    var detailCsvHeader = costumeNames.slice();
    var detailCsvRows = path.map(function (step) {
        return costumeNames.map(function (_, ci) {
            return String(step[ci]);
        });
    });
    window._bondDetailCsvData = JSON.stringify({
        header: detailCsvHeader,
        rows: detailCsvRows,
    });

    // --- 経験値 vs 絆ボーナス合計グラフ ---
    var cumExpData = [0]; // 累積経験値
    var totalBonusData = []; // 絆ボーナス合計値

    // 初期状態の絆ボーナス合計
    var initBonus = 0;
    for (var gi = 0; gi < costumeNames.length; gi++) {
        initBonus += cumPerCostume[gi][path[0][gi]];
    }
    totalBonusData.push(initBonus);

    for (var si = 1; si < path.length; si++) {
        // どの衣装が上がったか特定
        for (var sci = 0; sci < costumeNames.length; sci++) {
            if (path[si][sci] !== path[si - 1][sci]) {
                var prevRank = path[si - 1][sci];
                cumExpData.push(
                    cumExpData[si - 1] + _solver_BOND_EXP_PER_LEVEL[prevRank - 1]
                );
                break;
            }
        }
        var bonus = 0;
        for (var bci = 0; bci < costumeNames.length; bci++) {
            bonus += cumPerCostume[bci][path[si][bci]];
        }
        totalBonusData.push(bonus);
    }

    // --- 比較手法: 貪欲法 (毎ステップ p/w 最大を選択) ---
    var greedyExpData = [0];
    var greedyBonusData = [];
    var greedyState = currentRanks.slice();
    var greedyBonus = 0;
    for (var gri = 0; gri < costumeNames.length; gri++) {
        greedyBonus += cumPerCostume[gri][greedyState[gri]];
    }
    greedyBonusData.push(greedyBonus);
    var greedyTotal = path.length - 1; // Sidney と同じステップ数
    for (var gs = 0; gs < greedyTotal; gs++) {
        var bestCi = -1;
        var bestP = 0;
        var bestW = 1;
        for (var gci = 0; gci < costumeNames.length; gci++) {
            if (greedyState[gci] >= 50) continue;
            var gr = greedyState[gci];
            var gw = _solver_BOND_EXP_PER_LEVEL[gr - 1];
            var gp = cumPerCostume[gci][gr + 1] - cumPerCostume[gci][gr];
            // p/w 比較 (整数の交差乗算)
            if (bestCi === -1 || gp * bestW > bestP * gw) {
                bestCi = gci;
                bestP = gp;
                bestW = gw;
            }
        }
        if (bestCi === -1) break;
        var grw = _solver_BOND_EXP_PER_LEVEL[greedyState[bestCi] - 1];
        greedyExpData.push(greedyExpData[greedyExpData.length - 1] + grw);
        greedyState[bestCi]++;
        var grb = 0;
        for (var gbci = 0; gbci < costumeNames.length; gbci++) {
            grb += cumPerCostume[gbci][greedyState[gbci]];
        }
        greedyBonusData.push(grb);
    }

    // 要約チャートの各行に対応する縦線
    var vlineShapes = [];
    var vlineAnnotations = [];
    for (var vi = 0; vi < summary.length; vi++) {
        var xPos = cumExpData[summary[vi].end];
        if (xPos === undefined) continue;
        vlineShapes.push({
            type: "line",
            x0: xPos, x1: xPos,
            y0: 0, y1: 1,
            yref: "paper",
            line: { color: "rgba(150,150,150,0.5)", width: 1, dash: "dot" },
        });
        vlineAnnotations.push({
            x: xPos,
            y: 1,
            yref: "paper",
            text: String(vi + 1),
            showarrow: false,
            font: { size: 10, color: "#888" },
            yanchor: "bottom",
        });
    }

    var graphFigure = {
        data: [
            {
                name: "Sidney分解（最適）",
                x: cumExpData,
                y: totalBonusData,
                type: "scatter",
                mode: "lines",
                line: { color: "#2ecc71", width: 2.5, shape: "hv" },
                fill: "tozeroy",
                fillcolor: "rgba(46,204,113,0.1)",
            },
            {
                name: "貪欲法",
                x: greedyExpData,
                y: greedyBonusData,
                type: "scatter",
                mode: "lines",
                line: { color: "#e67e22", width: 1.5, shape: "hv" },
            },
        ],
        layout: {
            title: { text: "経験値 vs 絆ボーナス合計値" },
            xaxis: { title: { text: "累積経験値" } },
            yaxis: { title: { text: "絆ボーナス合計値" }, range: [initBonus, totalBonusData[totalBonusData.length - 1]] },
            legend: { x: 0.02, y: 0.98, bgcolor: "rgba(255,255,255,0.8)" },
            margin: { t: 40, r: 20, b: 50, l: 60 },
            height: 380,
            shapes: vlineShapes,
            annotations: vlineAnnotations,
        },
    };

    var graphComponent = {
        namespace: "dash_core_components",
        type: "Graph",
        props: {
            figure: graphFigure,
            config: {
                modeBarButtonsToRemove: [
                    "select2d",
                    "lasso2d",
                    "autoScale2d",
                ],
                displaylogo: false,
                toImageButtonOptions: {
                    format: "png",
                    filename: "bond_bonus_graph",
                    scale: 2,
                },
            },
            style: { marginTop: "16px" },
        },
    };

    // --- 結果コンポーネント ---
    return _solver_h("Div", {
        children: [
            _solver_h("Div", {
                children: [
                    _solver_h("H3", {
                        children: "\u8981\u7d04\u30c1\u30e3\u30fc\u30c8",
                        style: { marginBottom: "0" },
                    }),
                    _solver_h("Div", {
                        children: [
                            _solver_h("Button", {
                                children: "\u753b\u50cf\u4fdd\u5b58",
                                id: "save-image-btn",
                                n_clicks: 0,
                                className: "btn btn-sm",
                            }),
                            _solver_h("Button", {
                                children: "CSV\u4fdd\u5b58",
                                id: "save-csv-btn",
                                n_clicks: 0,
                                className: "btn btn-sm",
                            }),
                        ],
                        style: {
                            display: "flex",
                            gap: "8px",
                            marginLeft: "auto",
                        },
                    }),
                ],
                style: {
                    display: "flex",
                    alignItems: "center",
                    marginBottom: "8px",
                },
            }),
            _solver_h("Div", {
                children: summaryTable,
                id: "summary-table-container",
            }),
            _solver_h("Details", {
                children: [
                    _solver_h("Summary", {
                        children: "\u7d4c\u9a13\u5024 vs \u7d46\u30dc\u30fc\u30ca\u30b9\u30b0\u30e9\u30d5",
                        style: {
                            cursor: "pointer",
                            marginTop: "16px",
                            marginBottom: "8px",
                            fontWeight: "bold",
                        },
                    }),
                    graphComponent,
                ],
            }),
            _solver_h("Details", {
                children: [
                    _solver_h("Summary", {
                        children:
                            "\u8a73\u7d30\u30c1\u30e3\u30fc\u30c8\uff08\u5168\u30b9\u30c6\u30c3\u30d7\uff09",
                        style: {
                            cursor: "pointer",
                            marginTop: "16px",
                            marginBottom: "8px",
                            fontWeight: "bold",
                        },
                    }),
                    _solver_h("Div", {
                        children: [
                            _solver_h("Button", {
                                children: "\u753b\u50cf\u4fdd\u5b58",
                                id: "save-detail-image-btn",
                                n_clicks: 0,
                                className: "btn btn-sm",
                            }),
                            _solver_h("Button", {
                                children: "CSV\u4fdd\u5b58",
                                id: "save-detail-csv-btn",
                                n_clicks: 0,
                                className: "btn btn-sm",
                            }),
                        ],
                        style: {
                            display: "flex",
                            gap: "8px",
                            justifyContent: "flex-end",
                            marginBottom: "8px",
                        },
                    }),
                    _solver_h("Div", {
                        children: detailTable,
                        id: "detail-table-container",
                    }),
                ],
            }),
        ],
    });
}

/* ------------------------------------------------------------------ */
/*  Dash clientside_callback 登録                                      */
/* ------------------------------------------------------------------ */

window.dash_clientside = window.dash_clientside || {};
window.dash_clientside.solver = {
    /**
     * 絆ランク増減ボタン
     */
    bond_rank_inc_dec: function (incClicks, decClicks, values, rankIds, incIds, decIds) {
        var triggered = window.dash_clientside.callback_context.triggered;
        if (!triggered || triggered.length === 0 || !triggered[0].value) {
            return values.map(function () { return window.dash_clientside.no_update; });
        }
        var trigId = JSON.parse(triggered[0].prop_id.split(".")[0]);
        var targetIndex = trigId.index;
        var isInc = trigId.type === "bond-rank-inc";

        return rankIds.map(function (rid, i) {
            if (rid.index !== targetIndex) return window.dash_clientside.no_update;
            var cur = typeof values[i] === "number" ? values[i] : 20;
            return isInc ? Math.min(100, cur + 1) : Math.max(1, cur - 1);
        });
    },

    /**
     * ステップ1: スピナー表示 + 入力データを Store に格納
     */
    collect_inputs: function (
        n_clicks,
        rankValues,
        rankIds,
        bondValues,
        bondIds,
        costumeValues,
        costumeIds,
        costumePriorityOrder,
        bond50Penalty,
        costumeIcons
    ) {
        if (!n_clicks) return [
            window.dash_clientside.no_update,
            window.dash_clientside.no_update,
        ];

        // 絆ランクの範囲チェック
        var invalidNames = [];
        for (var ri = 0; ri < rankValues.length; ri++) {
            var rv = rankValues[ri];
            if (rv === null || rv === undefined || typeof rv !== "number" ||
                !isFinite(rv) || rv < 1 || rv > 100 || rv !== Math.floor(rv)) {
                var cidx = rankIds[ri] ? rankIds[ri].index : ri;
                var cname = null;
                for (var ci = 0; ci < costumeIds.length; ci++) {
                    if (costumeIds[ci].index === cidx) {
                        cname = costumeValues[ci];
                        break;
                    }
                }
                invalidNames.push(cname || _solver_defaultCostumeName(cidx));
            }
        }
        if (invalidNames.length > 0) {
            return [
                _solver_h("P", {
                    children: "絆ランクは1〜100の整数で入力してください（" + invalidNames.join("、") + "）。",
                    style: { color: "red", fontWeight: "bold" },
                }),
                window.dash_clientside.no_update,
            ];
        }

        // 全衣装の絆ランクが50以上の場合はエラー表示（Store は更新しない）
        var allMax = rankValues.every(function (r) { return r >= 50; });
        if (allMax) {
            return [
                _solver_h("P", {
                    children: "全ての衣装の絆ランクが50以上のため、計算できません。",
                    style: { color: "red", fontWeight: "bold" },
                }),
                window.dash_clientside.no_update,
            ];
        }

        // Store から優先度順序を取得
        var priorityOrder = [];
        if (costumePriorityOrder) {
            for (var i = 0; i < costumePriorityOrder.length; i++) {
                var entry = costumePriorityOrder[i];
                priorityOrder.push(typeof entry === "object" ? entry.idx : entry);
            }
        }

        var inputs = {
            rankValues: rankValues,
            rankIds: rankIds,
            bondValues: bondValues,
            bondIds: bondIds,
            costumeValues: costumeValues,
            costumeIds: costumeIds,
            costumePriorityOrder: priorityOrder,
            bond50Penalty: bond50Penalty || 0,
            costumeIcons: costumeIcons || {},
        };

        return [_solver_spinnerComponent(), inputs];
    },

    /**
     * ステップ2: Sidney 分解実行 + 結果表示
     */
    calc_chart: function (solverInputs) {
        if (!solverInputs) return window.dash_clientside.no_update;

        return new Promise(function (resolve) {
            setTimeout(function () {
                resolve(
                    _solver_calcChartSync(
                        solverInputs.rankValues,
                        solverInputs.rankIds,
                        solverInputs.bondValues,
                        solverInputs.bondIds,
                        solverInputs.costumeValues,
                        solverInputs.costumeIds,
                        solverInputs.costumePriorityOrder,
                        solverInputs.bond50Penalty,
                        solverInputs.costumeIcons
                    )
                );
            }, 50);
        });
    },
};
