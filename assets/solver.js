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
/*  階段状の折れ線グラフ（経験値 vs 絆ボーナス合計）                      */
/*  plotly（約1.4MB）を読み込まないよう自前で描く。文字は HTML、線は      */
/*  SVG 画像。横方向は % で配置するので、画面幅が変わっても文字の大きさは  */
/*  変わらず、線の画像だけが伸び縮みする（線の太さは変わらない）。幅が     */
/*  大きく変わったときは描き直す（下の resize）。                          */
/* ------------------------------------------------------------------ */

var _SOLVER_GRAPH_H = 380; // グラフ全体の高さ (px)
var _SOLVER_GRAPH_PAD = 4; // 端の線が切れないよう、線の画像を描画域より広げる幅 (px)
var _SOLVER_GRAPH_FONT =
    '"Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans JP", ' +
    '"Yu Gothic", YuGothic, Meiryo, sans-serif';

/** 目盛りのラベル（3桁区切り） */
function _solver_fmtNum(v) {
    return Number(v).toLocaleString("ja-JP");
}

/** 小数1桁に丸める（SVG の座標を短くする） */
function _solver_r1(v) {
    return Math.round(v * 10) / 10;
}

/** 0〜1 の割合を CSS の % にする */
function _solver_pct(f) {
    return Math.round(f * 100000) / 1000 + "%";
}

/**
 * lo〜hi のきりのよい目盛り（間隔は 1・2・2.5・5 × 10^n の整数）。
 * 隣の目盛りとの距離が minGap(ラベルの最大文字数) px 以上になる、
 * 最も細かい間隔を選ぶ。
 */
function _solver_niceTicks(lo, hi, lengthPx, minGap) {
    var span = hi - lo;
    var mults = [1, 2, 2.5, 5];
    for (var mag = 1; mag < 1e15; mag *= 10) {
        for (var mi = 0; mi < mults.length; mi++) {
            var step = mults[mi] * mag;
            if (step !== Math.floor(step)) continue;
            var first = Math.ceil(lo / step) * step;
            var last = Math.floor(hi / step) * step;
            var chars = Math.max(
                _solver_fmtNum(first).length,
                _solver_fmtNum(last).length
            );
            if (step >= span || (step / span) * lengthPx >= minGap(chars)) {
                var ticks = [];
                for (var v = first; v <= hi; v += step) ticks.push(v);
                return ticks;
            }
        }
    }
    return [lo];
}

/** 階段状（横 → 縦）の折れ線の SVG パス */
function _solver_stepPath(xs, ys, X, Y) {
    var n = Math.min(xs.length, ys.length);
    var d = "M" + X(xs[0]) + " " + Y(ys[0]);
    for (var i = 1; i < n; i++) {
        d += "H" + X(xs[i]);
        if (ys[i] !== ys[i - 1]) d += "V" + Y(ys[i]);
    }
    return d;
}

/** 結果エリアの幅 (px)。グラフの余白・目盛りの数を決めるのに使う */
function _solver_graphWidth() {
    var el = document.getElementById("chart-result");
    if (!el || !el.clientWidth) return 800;
    var cs = window.getComputedStyle(el);
    var w =
        el.clientWidth -
        (parseFloat(cs.paddingLeft) || 0) -
        (parseFloat(cs.paddingRight) || 0);
    return Math.max(w, 260);
}

// 直近に描いたグラフ { opts, width }（画面幅が変わったときの描き直しに使う）
var _solver_lastGraph = null;

/**
 * 階段状の折れ線グラフのコンポーネント（id="bond-graph"）。
 *   opts.series: [{name, xs, ys, color, width, fill(省略可)}]（後ろほど手前に描く）
 *   opts.vlines: [{x, label}]（点線の縦線と、その上の番号）
 *   opts.title / opts.xTitle / opts.yTitle / opts.alt
 * 横軸は 0〜最大値、縦軸は最小値〜最大値。
 */
function _solver_stepChart(opts) {
    var H = _SOLVER_GRAPH_H;
    var P = _SOLVER_GRAPH_PAD;
    var W = _solver_graphWidth();
    _solver_lastGraph = { opts: opts, width: W };
    var series = opts.series;
    var xMin = 0;
    var xMax = 0;
    var yMin = Infinity;
    var yMax = -Infinity;
    series.forEach(function (s) {
        s.xs.forEach(function (x) {
            if (x > xMax) xMax = x;
        });
        s.ys.forEach(function (y) {
            if (y < yMin) yMin = y;
            if (y > yMax) yMax = y;
        });
    });
    if (!isFinite(yMin)) {
        yMin = 0;
        yMax = 1;
    }
    if (!(xMax > xMin)) xMax = xMin + 1;
    if (!(yMax > yMin)) yMax = yMin + 1;

    // 余白: 上 T（タイトル・凡例・縦線の番号）、下 B（横軸）、左 L（縦軸）、右 R
    var B = 40;
    var R = 16;
    var yTicks = _solver_niceTicks(yMin, yMax, H - 84 - B, function () {
        return 30;
    });
    var yChars = 1;
    yTicks.forEach(function (v) {
        yChars = Math.max(yChars, _solver_fmtNum(v).length);
    });
    var L = Math.ceil(30 + yChars * 6.5);
    var plotW = Math.max(W - L - R, 100);
    var xTicks = _solver_niceTicks(xMin, xMax, plotW, function (chars) {
        return chars * 6.5 + 36;
    });
    function fx(x) {
        return (x - xMin) / (xMax - xMin);
    }

    // 縦線の番号は、前の番号と近いときは上の段にずらす（最大3段。どの段も
    // 空いていなければ一番空いている段）
    var rowEnd = [-Infinity, -Infinity, -Infinity];
    var rows = 1;
    var vlines = opts.vlines.map(function (v) {
        var px = fx(v.x) * plotW;
        var half = (String(v.label).length * 6 + 2) / 2;
        var row = -1;
        for (var r = 0; r < rowEnd.length && row < 0; r++) {
            if (px - half >= rowEnd[r] + 6) row = r;
        }
        if (row < 0) row = rowEnd.indexOf(Math.min.apply(null, rowEnd));
        rowEnd[row] = px + half;
        rows = Math.max(rows, row + 1);
        return { x: v.x, label: String(v.label), row: row };
    });
    var T = 48 + rows * 12;
    var plotH = H - T - B;

    // --- 線（SVG 画像）。座標は描いた時点の px（上下左右に P の余白） ---
    function X(x) {
        return _solver_r1(P + fx(x) * plotW);
    }
    function Y(y) {
        return _solver_r1(P + (1 - (y - yMin) / (yMax - yMin)) * plotH);
    }
    var left = P;
    var right = _solver_r1(P + plotW);
    var top = P;
    var bottom = _solver_r1(P + plotH);
    var noScale = ' fill="none" vector-effect="non-scaling-stroke"';
    var crisp = noScale + ' shape-rendering="crispEdges"';
    var grid = "";
    yTicks.forEach(function (v) {
        grid += "M" + left + " " + Y(v) + "H" + right;
    });
    xTicks.forEach(function (v) {
        grid += "M" + X(v) + " " + top + "V" + bottom;
    });
    var svg = [
        '<path d="' + grid + '" stroke="#eceff3"' + crisp + "/>",
        '<path d="M' + left + " " + top + "V" + bottom + "H" + right +
            '" stroke="#c4cad3"' + crisp + "/>",
    ];
    series.forEach(function (s) {
        if (!s.fill) return;
        svg.push(
            '<path d="' + _solver_stepPath(s.xs, s.ys, X, Y) + "V" + bottom +
                "H" + X(s.xs[0]) + 'Z" fill="' + s.fill + '"/>'
        );
    });
    series.forEach(function (s) {
        svg.push(
            '<path d="' + _solver_stepPath(s.xs, s.ys, X, Y) + '" stroke="' +
                s.color + '" stroke-width="' + s.width + '"' + noScale + "/>"
        );
    });
    var vd = "";
    vlines.forEach(function (v) {
        vd += "M" + X(v.x) + " " + top + "V" + bottom;
    });
    if (vd) {
        svg.push(
            '<path d="' + vd + '" stroke="rgba(150,150,150,0.6)"' +
                ' stroke-dasharray="3 3"' + crisp + "/>"
        );
    }
    var vw = _solver_r1(plotW + 2 * P);
    var vh = _solver_r1(plotH + 2 * P);
    var src =
        "data:image/svg+xml," +
        encodeURIComponent(
            '<svg xmlns="http://www.w3.org/2000/svg" width="' + vw +
                '" height="' + vh + '" viewBox="0 0 ' + vw + " " + vh +
                '" preserveAspectRatio="none">' + svg.join("") + "</svg>"
        );

    // --- 文字（HTML）。描画域（plot）を基準に % / px で置く ---
    var tick = {
        position: "absolute",
        fontSize: "11px",
        lineHeight: "14px",
        color: "#666",
        whiteSpace: "nowrap",
    };
    var plot = [
        _solver_h("Img", {
            src: src,
            alt: opts.alt,
            style: {
                position: "absolute",
                left: -P + "px",
                top: -P + "px",
                width: "calc(100% + " + 2 * P + "px)",
                height: vh + "px",
                maxWidth: "none",
                display: "block",
            },
        }),
    ];
    yTicks.forEach(function (v) {
        plot.push(
            _solver_h("Div", {
                children: _solver_fmtNum(v),
                style: Object.assign({}, tick, {
                    right: "calc(100% + 6px)",
                    top: Y(v) - P + "px",
                    transform: "translateY(-50%)",
                }),
            })
        );
    });
    xTicks.forEach(function (v) {
        var text = _solver_fmtNum(v);
        // 右端のラベルがはみ出すときは左に寄せる
        var over = Math.max(0, fx(v) * plotW + (text.length * 6.5) / 2 - plotW - R + 2);
        plot.push(
            _solver_h("Div", {
                children: text,
                style: Object.assign({}, tick, {
                    left: _solver_pct(fx(v)),
                    top: "calc(100% + 5px)",
                    transform: "translateX(calc(-50% - " + Math.ceil(over) + "px))",
                }),
            })
        );
    });
    vlines.forEach(function (v) {
        plot.push(
            _solver_h("Div", {
                children: v.label,
                style: {
                    position: "absolute",
                    left: _solver_pct(fx(v.x)),
                    bottom: "calc(100% + " + (2 + v.row * 12) + "px)",
                    transform: "translateX(-50%)",
                    fontSize: "10px",
                    lineHeight: "12px",
                    color: "#888",
                },
            })
        );
    });

    var legend = series.map(function (s) {
        return _solver_h("Span", {
            children: [
                _solver_h("Span", {
                    style: {
                        display: "inline-block",
                        width: "22px",
                        height: s.fill ? "8px" : "0",
                        borderTop: s.width + "px solid " + s.color,
                        background: s.fill || "transparent",
                        verticalAlign: "middle",
                        marginRight: "6px",
                    },
                }),
                s.name,
            ],
            style: { whiteSpace: "nowrap" },
        });
    });

    return _solver_h("Div", {
        id: "bond-graph",
        children: [
            _solver_h("Div", {
                children: opts.title,
                style: {
                    position: "absolute",
                    top: "2px",
                    left: 0,
                    right: 0,
                    textAlign: "center",
                    fontSize: "15px",
                    lineHeight: "22px",
                    color: "#333",
                },
            }),
            _solver_h("Div", {
                children: legend,
                style: {
                    position: "absolute",
                    top: "26px",
                    left: 0,
                    right: 0,
                    display: "flex",
                    flexWrap: "wrap",
                    justifyContent: "center",
                    gap: "0 16px",
                    fontSize: "12px",
                    lineHeight: "18px",
                    color: "#444",
                },
            }),
            _solver_h("Div", {
                children: plot,
                style: {
                    position: "absolute",
                    left: L + "px",
                    right: R + "px",
                    top: T + "px",
                    height: plotH + "px",
                },
            }),
            _solver_h("Div", {
                children: opts.yTitle,
                style: {
                    position: "absolute",
                    left: "12px",
                    top: T + plotH / 2 + "px",
                    transform: "translate(-50%, -50%) rotate(-90deg)",
                    whiteSpace: "nowrap",
                    fontSize: "12px",
                    lineHeight: "16px",
                    color: "#444",
                },
            }),
            _solver_h("Div", {
                children: opts.xTitle,
                style: {
                    position: "absolute",
                    left: L + "px",
                    right: R + "px",
                    bottom: "2px",
                    textAlign: "center",
                    fontSize: "12px",
                    lineHeight: "16px",
                    color: "#444",
                },
            }),
        ],
        style: {
            position: "relative",
            height: H + "px",
            overflow: "hidden",
            background: "#fff",
            fontFamily: _SOLVER_GRAPH_FONT,
        },
    });
}

/*
 * 画面幅が大きく変わったら（回転・ウィンドウの幅の変更）、目盛りの数や縦線の
 * 番号の段を決め直してグラフを描き直す。それまでの間は線の画像が伸び縮みする。
 */
var _solver_resizeTimer = null;
window.addEventListener("resize", function () {
    clearTimeout(_solver_resizeTimer);
    _solver_resizeTimer = setTimeout(function () {
        var last = _solver_lastGraph;
        var dc = window.dash_clientside;
        if (!last || !dc || !dc.set_props) return;
        if (!document.getElementById("bond-graph")) return;
        if (Math.abs(_solver_graphWidth() - last.width) < 40) return;
        dc.set_props("bond-graph", {
            children: _solver_stepChart(last.opts).props.children,
        });
    }, 200);
});

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

    // 要約チャートの各行に対応する縦線（番号 = 要約チャートの行番号）
    var vlines = [];
    for (var vi = 0; vi < summary.length; vi++) {
        var xPos = cumExpData[summary[vi].end];
        if (xPos === undefined) continue;
        vlines.push({ x: xPos, label: vi + 1 });
    }

    var graphComponent = _solver_stepChart({
        title: "経験値 vs 絆ボーナス合計値",
        xTitle: "累積経験値",
        yTitle: "絆ボーナス合計値",
        alt: "累積経験値ごとの絆ボーナス合計値の推移",
        series: [
            {
                name: "Sidney分解（最適）",
                xs: cumExpData,
                ys: totalBonusData,
                color: "#2ecc71",
                width: 2.5,
                fill: "rgba(46,204,113,0.1)",
            },
            {
                name: "貪欲法",
                xs: greedyExpData,
                ys: greedyBonusData,
                color: "#e67e22",
                width: 1.5,
            },
        ],
        vlines: vlines,
    });

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
                    _solver_h("Div", {
                        children: _solver_h("Button", {
                            children: "画像保存",
                            id: "save-graph-image-btn",
                            n_clicks: 0,
                            className: "btn btn-sm",
                        }),
                        style: {
                            display: "flex",
                            justifyContent: "flex-end",
                            marginBottom: "8px",
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
