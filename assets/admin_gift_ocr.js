/**
 * 好みの贈り物のスクリーンショット読み取り（管理画面の衣装追加・好み編集）
 *
 * ゲームの生徒プロフィールの「好みの贈り物」パネルのスクリーンショットから、
 * 贈り物ごとの好み (tier) を読み取り、ページの好みのラジオに入れる。
 * パネルには全贈り物が 1 回ずつ並び、顔アイコンの見出しで 4 段（上から
 * ultra / super / favorite / normal）に分かれている。
 *   1. 桃色の見出し帯「好みの贈り物」を目印にパネルを見つける
 *   2. 中央の顔アイコン (assets/reaction) で段の境目と段の種類を決める
 *   3. 5 列の格子のカードを贈り物アイコン (assets/gift) と比べる。
 *      背景色（紫 = 高級・黄 = 通常）で候補を絞り、1 枚の画像の中で
 *      同じ贈り物が 2 回出ないように割り当てる
 * 位置・大きさはすべて見出し帯の幅を基準にした比なので、画面の解像度に依らない。
 * 処理はすべてブラウザ内で行い、画像はサーバーへ送らない。
 *
 * 画像処理の関数は {data, width, height}（RGBA の ImageData 相当）だけを
 * 扱い、DOM に依存しない（Node でも動かせる）。
 */

/* ------------------------------------------------------------------ */
/*  定数（見出し帯の幅 = 1 とした比。1749x984 のスクリーンショットで計測）   */
/* ------------------------------------------------------------------ */

// パネルの中身の下端（見出し帯の上端から）。
var _giftOcr_CONTENT_BOTTOM = 1.147;
// カードの列: 1 列目の左端（見出し帯の左端から）・列の間隔・カードの幅と高さ。
var _giftOcr_COL_LEFT = 0.0553;
var _giftOcr_COL_PITCH = 0.1862;
var _giftOcr_CARD_W = 0.164;
var _giftOcr_CARD_H = 0.152;
var _giftOcr_COLS = 5;
// 顔アイコンの中心の x（見出し帯の左端から）。
var _giftOcr_FACE_X = 0.498;

// 贈り物アイコン（72x56）を置く位置（カードの幅 = 1 とした比）と照合の大きさ。
var _giftOcr_ICON_LEFT = -0.09;
var _giftOcr_ICON_TOP = 0.05;
var _giftOcr_ICON_W = 1.07;
var _giftOcr_MATCH_W = 36;
var _giftOcr_MATCH_H = 28;

// 照合の得点で色の差にかける重み（_giftOcr_ncc）。
// 見本 6 枚（3 衣装）では 0.5〜3 で誤りが無く、2 以上で要確認が最も少なかった。
var _giftOcr_COLOR_W = 2;

// 段の名前（パネルの上から順）。
var _giftOcr_TIERS = ["ultra", "super", "favorite", "normal"];

// 照合を「要確認」にする閾値（1 位と 2 位の得点差・得点）。
// 見本 9 枚（4 衣装・181 カード）で、正しい照合の得点差は最小 0.40、得点は最小 0.57。
// 贈り物を 1 つずつ照合用データから外すと（贈り物の画像が無い新しい贈り物の
// 代わり）、そのカードの得点は最大 0.36 だった。
var _giftOcr_MIN_MARGIN = 0.08;
var _giftOcr_MIN_SCORE = 0.45;

/* ------------------------------------------------------------------ */
/*  画像処理                                                           */
/* ------------------------------------------------------------------ */

/** 見出し帯の桃色 (255, 164, 199) か。 */
function _giftOcr_isPink(d, o) {
    var r = d[o], g = d[o + 1], b = d[o + 2];
    return r >= 235 && g >= 140 && g <= 200 && b >= 170 && b <= 225;
}

/**
 * 「好みの贈り物」の見出し帯を探す。Returns {x0, x1, y0, y1, unit: 帯の幅} か null。
 *
 * 桃色の画素が横に長く続く行の帯のうち、最も幅の広いもの。帯の中の白い文字・
 * ×ボタンで途切れないよう、行ごとに近い桃色の区間（すき間が画像の幅の 5% 以下）を
 * つないだ最も広い区間を使う。
 */
function _giftOcr_findHeader(img) {
    var w = img.width, h = img.height, d = img.data;
    var maxGap = 0.05 * w;
    var best = null, run = null;
    for (var y = 0; y <= h; y++) {
        var x0 = -1, x1 = -1, n = 0;
        if (y < h) {
            var s0 = -1, s1 = -1, sn = 0;
            for (var x = 0; x <= w; x++) {
                var pink = x < w && _giftOcr_isPink(d, (y * w + x) * 4);
                if (pink && s0 >= 0 && x - s1 > maxGap) {
                    if (s1 - s0 > x1 - x0) { x0 = s0; x1 = s1; n = sn; }
                    s0 = -1;
                }
                if (pink) {
                    if (s0 < 0) { s0 = x; sn = 0; }
                    s1 = x;
                    sn++;
                }
            }
            if (s0 >= 0 && s1 - s0 > x1 - x0) { x0 = s0; x1 = s1; n = sn; }
        }
        // 帯の行: 区間の 6 割以上が桃色で、画像の幅の 15% 以上
        var ok = x0 >= 0 && x1 - x0 + 1 >= 0.15 * w && n >= 0.6 * (x1 - x0 + 1);
        if (ok && run && Math.abs(x0 - run.x0) <= 3 && Math.abs(x1 - run.x1) <= 3) {
            run.y1 = y;
        } else {
            if (run && run.y1 - run.y0 + 1 >= 0.06 * (run.x1 - run.x0 + 1)
                && (!best || run.x1 - run.x0 > best.x1 - best.x0)) {
                best = run;
            }
            run = ok ? { x0: x0, x1: x1, y0: y, y1: y } : null;
        }
    }
    if (!best) return null;
    best.unit = best.x1 - best.x0 + 1;
    return best;
}

/**
 * img の矩形 (left, top, width, height)（小数可）を ow x oh に縮小した
 * RGB（Float32Array, 長さ ow*oh*3）と透明度（Float32Array, 長さ ow*oh）。
 * 各出力画素は対応する範囲の画素の平均。
 */
function _giftOcr_resample(img, left, top, width, height, ow, oh) {
    var d = img.data, rgb = new Float32Array(ow * oh * 3), alpha = new Float32Array(ow * oh);
    for (var oy = 0; oy < oh; oy++) {
        var sy0 = Math.max(0, Math.floor(top + oy * height / oh));
        var sy1 = Math.min(img.height, Math.max(sy0 + 1, Math.floor(top + (oy + 1) * height / oh)));
        for (var ox = 0; ox < ow; ox++) {
            var sx0 = Math.max(0, Math.floor(left + ox * width / ow));
            var sx1 = Math.min(img.width, Math.max(sx0 + 1, Math.floor(left + (ox + 1) * width / ow)));
            var r = 0, g = 0, b = 0, a = 0, n = 0;
            for (var y = sy0; y < sy1; y++) {
                for (var x = sx0; x < sx1; x++) {
                    var o = (y * img.width + x) * 4, ai = d[o + 3] / 255;
                    r += d[o] * ai; g += d[o + 1] * ai; b += d[o + 2] * ai;
                    a += ai;
                    n++;
                }
            }
            var k = oy * ow + ox;
            // 色は透明度で割り戻す（縁の半透明の画素が白・黒に寄らないように）
            rgb[k * 3] = a ? r / a : 255;
            rgb[k * 3 + 1] = a ? g / a : 255;
            rgb[k * 3 + 2] = a ? b / a : 255;
            alpha[k] = n ? a / n : 0;
        }
    }
    return { rgb: rgb, alpha: alpha };
}

/** 矩形 (x0..x1, y0..y1) で「白くない」画素の割合。 */
function _giftOcr_coloredFraction(img, x0, y0, x1, y1) {
    var d = img.data, n = 0, c = 0;
    x0 = Math.max(0, Math.round(x0)); x1 = Math.min(img.width - 1, Math.round(x1));
    y0 = Math.max(0, Math.round(y0)); y1 = Math.min(img.height - 1, Math.round(y1));
    for (var y = y0; y <= y1; y++) {
        for (var x = x0; x <= x1; x++) {
            var o = (y * img.width + x) * 4;
            if (765 - d[o] - d[o + 1] - d[o + 2] > 45) c++;
            n++;
        }
    }
    return n ? c / n : 0;
}

/** 顔アイコンの紺色の線か。 */
function _giftOcr_isNavy(d, o) {
    var r = d[o], g = d[o + 1], b = d[o + 2];
    return b - r >= 25 && r + g + b <= 500;
}

/**
 * 1 列目のカードの上端の y のリスト（上から順）。各要素は {top, cut}。
 * cut はパネルの上端・下端で切れているカード。
 *
 * 1 列目の帯で白くない画素が半分以上の行が続く所をカードとみなす（カードの
 * 下の影の細い線は除く）。カードの下の方は白っぽいので、上端から CARD_H の
 * あいだに始まる帯は同じカードとして扱う。
 */
function _giftOcr_findRows(img, panel) {
    var u = panel.unit;
    var bandX0 = panel.x0 + (_giftOcr_COL_LEFT + 0.15 * _giftOcr_CARD_W) * u;
    var bandX1 = panel.x0 + (_giftOcr_COL_LEFT + 0.85 * _giftOcr_CARD_W) * u;
    var cardH = _giftOcr_CARD_H * u;
    var minRun = 0.03 * u;
    var rows = [], start = -1;
    for (var y = panel.top; y <= panel.bottom + 1; y++) {
        var on = y <= panel.bottom
            && _giftOcr_coloredFraction(img, bandX0, y, bandX1, y) >= 0.5;
        if (on && start < 0) start = y;
        if (!on && start >= 0) {
            var last = rows[rows.length - 1];
            if (y - start >= minRun && (!last || start >= last.top + 0.9 * cardH)) {
                rows.push({
                    top: start,
                    cut: start <= panel.top + 1 || start + cardH > panel.bottom + 1,
                });
            }
            start = -1;
        }
    }
    return rows;
}

/**
 * 顔アイコンを探す。Returns [{y0, y1, x0, x1}]（カードの行の外だけを探す）。
 * パネルの上端・下端で切れている顔は除く。
 */
function _giftOcr_findFaces(img, panel, rows) {
    var u = panel.unit, d = img.data;
    var cx = panel.x0 + _giftOcr_FACE_X * u;
    var x0 = Math.round(cx - 0.045 * u), x1 = Math.round(cx + 0.045 * u);
    var cardH = _giftOcr_CARD_H * u;
    // 輪の横の線は細く、JPEG のにじみで途切れるので、このすき間まではつなぐ
    var maxGap = 0.015 * u;
    function inCard(y) {
        return rows.some(function (r) { return y >= r.top - 2 && y <= r.top + cardH; });
    }
    var faces = [], run = null;
    function close() {
        if (run && run.y1 - run.y0 + 1 >= 0.04 * u
            && run.y0 > panel.top + 1 && run.y1 < panel.bottom) {
            faces.push(run);
        }
        run = null;
    }
    for (var y = panel.top; y <= panel.bottom; y++) {
        if (inCard(y)) { close(); continue; }
        var fx0 = -1, fx1 = -1;
        for (var x = x0; x <= x1; x++) {
            if (_giftOcr_isNavy(d, (y * img.width + x) * 4)) {
                if (fx0 < 0) fx0 = x;
                fx1 = x;
            }
        }
        if (fx0 < 0) continue;
        if (run && y - run.y1 > maxGap) close();
        if (!run) run = { y0: y, y1: y, x0: fx0, x1: fx1 };
        run.y1 = y;
        run.x0 = Math.min(run.x0, fx0);
        run.x1 = Math.max(run.x1, fx1);
    }
    close();
    return faces;
}

// 顔アイコンの照合の大きさ。
var _giftOcr_FACE_N = 20;

/** 顔アイコンの外接矩形を FACE_N x FACE_N に縮めた輝度。 */
function _giftOcr_faceFeature(img, box) {
    var s = _giftOcr_resample(img, box.x0, box.y0, box.x1 - box.x0 + 1, box.y1 - box.y0 + 1,
        _giftOcr_FACE_N, _giftOcr_FACE_N);
    var out = new Float32Array(_giftOcr_FACE_N * _giftOcr_FACE_N);
    for (var i = 0; i < out.length; i++) {
        var a = s.alpha[i];
        // 透明な画素は白と合成する（assets/reaction の PNG の外側）
        var l = 0.299 * s.rgb[i * 3] + 0.587 * s.rgb[i * 3 + 1] + 0.114 * s.rgb[i * 3 + 2];
        out[i] = l * a + 255 * (1 - a);
    }
    return out;
}

/** assets/reaction の画像から、紺色の輪の外接矩形を切り出した特徴。 */
function _giftOcr_reactionFeature(img) {
    var d = img.data, box = { x0: img.width, x1: -1, y0: img.height, y1: -1 };
    for (var y = 0; y < img.height; y++) {
        for (var x = 0; x < img.width; x++) {
            var o = (y * img.width + x) * 4;
            if (d[o + 3] >= 128 && _giftOcr_isNavy(d, o)) {
                box.x0 = Math.min(box.x0, x); box.x1 = Math.max(box.x1, x);
                box.y0 = Math.min(box.y0, y); box.y1 = Math.max(box.y1, y);
            }
        }
    }
    if (box.x1 < 0) box = { x0: 0, x1: img.width - 1, y0: 0, y1: img.height - 1 };
    return _giftOcr_faceFeature(img, box);
}

/** 顔アイコンの段の種類。faceRefs は {tier: 特徴}。 */
function _giftOcr_classifyFace(img, box, faceRefs) {
    var f = _giftOcr_faceFeature(img, box), best = null, bestDist = Infinity;
    Object.keys(faceRefs).forEach(function (tier) {
        var r = faceRefs[tier], sum = 0;
        for (var i = 0; i < f.length; i++) sum += (f[i] - r[i]) * (f[i] - r[i]);
        if (sum < bestDist) { bestDist = sum; best = tier; }
    });
    return best;
}

/** カードの背景が紫（高級の贈り物）か。カードの左上の色で決める。 */
function _giftOcr_isHighCard(img, card) {
    var s = _giftOcr_resample(img, card.left + 0.06 * card.width, card.top + 0.08 * card.height,
        0.1 * card.width, 0.1 * card.height, 1, 1).rgb;
    return s[2] > s[1] + 20;
}

/**
 * 贈り物の画像（RGBA, 72x56）を照合用の特徴にする。
 * Returns {idx: 不透明な画素の番号, v: その RGB（平均を引き、長さ 1 に正規化）}。
 */
function _giftOcr_giftFeature(img) {
    var s = _giftOcr_resample(img, 0, 0, img.width, img.height, _giftOcr_MATCH_W, _giftOcr_MATCH_H);
    var idx = [];
    for (var i = 0; i < s.alpha.length; i++) if (s.alpha[i] >= 0.5) idx.push(i);
    var v = new Float32Array(idx.length * 3), raw = new Float32Array(idx.length * 3), mean = 0;
    idx.forEach(function (p, j) {
        for (var c = 0; c < 3; c++) {
            raw[j * 3 + c] = v[j * 3 + c] = s.rgb[p * 3 + c];
            mean += s.rgb[p * 3 + c];
        }
    });
    mean /= v.length || 1;
    var norm = 0;
    for (var j = 0; j < v.length; j++) { v[j] -= mean; norm += v[j] * v[j]; }
    norm = Math.sqrt(norm) || 1;
    for (var k = 0; k < v.length; k++) v[k] /= norm;
    return { idx: idx, v: v, raw: raw };
}

/**
 * 切り出し (rgb) と贈り物の特徴の得点。正規化相互相関 (-1〜1) から、色の差
 * （平均の絶対差 / 255）の COLOR_W 倍を引く。相関だけだと、淡い色の贈り物
 * （本・布）がカードの背景に近い色の贈り物に負けるため。
 */
function _giftOcr_ncc(rgb, ref) {
    var idx = ref.idx, v = ref.v, raw = ref.raw, n = idx.length * 3, mean = 0, diff = 0;
    for (var j = 0; j < idx.length; j++) {
        var k = idx[j] * 3;
        mean += rgb[k] + rgb[k + 1] + rgb[k + 2];
    }
    mean /= n || 1;
    var dot = 0, norm = 0;
    for (var j2 = 0; j2 < idx.length; j2++) {
        var k2 = idx[j2] * 3;
        for (var c = 0; c < 3; c++) {
            var a = rgb[k2 + c] - mean;
            dot += a * v[j2 * 3 + c];
            norm += a * a;
            diff += Math.abs(rgb[k2 + c] - raw[j2 * 3 + c]);
        }
    }
    return (norm ? dot / Math.sqrt(norm) : 0) - _giftOcr_COLOR_W * diff / (n || 1) / 255;
}

/**
 * カードと各贈り物の得点（位置・大きさを少しずらした切り出しの最大）。
 * refs は [{id, high, all, feature}]。Returns 得点の配列（背景色に合わない贈り物は -Infinity）。
 */
function _giftOcr_scoreCard(img, card, refs) {
    var high = _giftOcr_isHighCard(img, card);
    var crops = [];
    [0.96, 1, 1.04].forEach(function (scale) {
        var iw = _giftOcr_ICON_W * scale * card.width;
        var ih = iw * 56 / 72;
        var cx = card.left + (_giftOcr_ICON_LEFT + _giftOcr_ICON_W / 2) * card.width;
        var cy = card.top + _giftOcr_ICON_TOP * card.width + _giftOcr_ICON_W * card.width * 56 / 72 / 2;
        var step = 0.02 * card.width;
        for (var dy = -2; dy <= 2; dy++) {
            for (var dx = -2; dx <= 2; dx++) {
                crops.push(_giftOcr_resample(img, cx - iw / 2 + dx * step, cy - ih / 2 + dy * step,
                    iw, ih, _giftOcr_MATCH_W, _giftOcr_MATCH_H).rgb);
            }
        }
    });
    return refs.map(function (ref) {
        // 花束など全員共通の贈り物 (*-all) はどちらの背景にも出る
        if (!ref.all && ref.high !== high) return -Infinity;
        var best = -Infinity;
        for (var i = 0; i < crops.length; i++) best = Math.max(best, _giftOcr_ncc(crops[i], ref.feature));
        return best;
    });
}

/**
 * 割り当て問題（ハンガリー法）。cost は n 行 m 列 (n <= m)。
 * Returns 各行に割り当てた列の番号。
 */
function _giftOcr_assign(cost) {
    var n = cost.length, m = n ? cost[0].length : 0;
    var INF = 1e18;
    var u = new Float64Array(n + 1), v = new Float64Array(m + 1);
    var p = new Int32Array(m + 1), way = new Int32Array(m + 1);
    for (var i = 1; i <= n; i++) {
        p[0] = i;
        var j0 = 0;
        var minv = new Float64Array(m + 1).fill(INF);
        var used = new Uint8Array(m + 1);
        do {
            used[j0] = 1;
            var i0 = p[j0], delta = INF, j1 = 0;
            for (var j = 1; j <= m; j++) {
                if (used[j]) continue;
                var cur = cost[i0 - 1][j - 1] - u[i0] - v[j];
                if (cur < minv[j]) { minv[j] = cur; way[j] = j0; }
                if (minv[j] < delta) { delta = minv[j]; j1 = j; }
            }
            for (var j2 = 0; j2 <= m; j2++) {
                if (used[j2]) { u[p[j2]] += delta; v[j2] -= delta; } else { minv[j2] -= delta; }
            }
            j0 = j1;
        } while (p[j0] !== 0);
        do {
            var jPrev = way[j0];
            p[j0] = p[jPrev];
            j0 = jPrev;
        } while (j0);
    }
    var out = new Array(n);
    for (var jj = 1; jj <= m; jj++) if (p[jj]) out[p[jj] - 1] = jj - 1;
    return out;
}

/**
 * 1 枚のスクリーンショットを読む。refs は贈り物の照合用データ、faceRefs は顔アイコン。
 * Returns {cells: [{gift, tier, uncertain, unknown, score, margin, rect}], found: パネルを見つけたか}。
 * tier は段の見出しが画像に写っていないカードでは null。unknown は得点が低く、
 * 贈り物の画像が無い（新しい）贈り物かもしれないカード。rect はカードの矩形。
 */
function _giftOcr_readImage(img, refs, faceRefs) {
    var hdr = _giftOcr_findHeader(img);
    if (!hdr) return { cells: [], found: false };
    var u = hdr.unit;
    var panel = {
        x0: hdr.x0, unit: u, top: hdr.y1 + 1,
        bottom: Math.min(img.height - 1, Math.round(hdr.y0 + _giftOcr_CONTENT_BOTTOM * u)),
    };
    var rows = _giftOcr_findRows(img, panel);
    var faces = _giftOcr_findFaces(img, panel, rows).map(function (f) {
        return { y: f.y0, tier: _giftOcr_classifyFace(img, f, faceRefs) };
    });

    var cards = [];
    rows.forEach(function (row) {
        if (row.cut) return;
        var tier = null;
        faces.forEach(function (f) { if (f.y < row.top) tier = f.tier; });
        for (var c = 0; c < _giftOcr_COLS; c++) {
            var card = {
                left: panel.x0 + (_giftOcr_COL_LEFT + c * _giftOcr_COL_PITCH) * u,
                top: row.top,
                width: _giftOcr_CARD_W * u,
                height: _giftOcr_CARD_H * u,
            };
            // 行は左から詰めて並ぶ。空いた所で終わり
            if (_giftOcr_coloredFraction(img, card.left + 0.15 * card.width, card.top + 0.1 * card.height,
                card.left + 0.85 * card.width, card.top + 0.5 * card.height) < 0.5) break;
            cards.push({ rect: card, tier: tier });
        }
    });
    if (!cards.length) return { cells: [], found: true };

    var scored = cards.map(function (c) { return _giftOcr_scoreCard(img, c.rect, refs); });
    var cost = scored.map(function (s) {
        return s.map(function (v) { return v === -Infinity ? 1e6 : -v; });
    });
    var assigned = _giftOcr_assign(cost);
    var cells = cards.map(function (c, i) {
        var s = scored[i], j = assigned[i];
        var top = -Infinity, second = -Infinity;
        s.forEach(function (v) {
            if (v > top) { second = top; top = v; } else if (v > second) { second = v; }
        });
        // 1 位でない贈り物を割り当てた・1 位と 2 位の差が小さい・得点が低いカードは要確認
        var unknown = !(s[j] >= _giftOcr_MIN_SCORE);
        var uncertain = unknown || s[j] < top || top - second < _giftOcr_MIN_MARGIN;
        return {
            gift: refs[j].id, tier: c.tier, uncertain: uncertain, unknown: unknown,
            score: s[j], margin: top - second, rect: c.rect,
        };
    });
    return { cells: cells, found: true };
}

/**
 * 複数の画像の読み取り結果をまとめる。
 * Returns {gifts: {贈り物ID: {tier, uncertain}}, conflicts: [ID],
 *          unknowns: [{gift: 最も近い贈り物ID, tier, crop}]}。
 *
 * 段の見出しが写っていないカード (tier = null) は、1 枚の画像の中では
 * どれも同じ段にある。そのうちのどれかを別の画像で見出し付きで読んでいれば、
 * その段をまとめて使う。段が食い違う贈り物は要確認にする（確かな読み取りが
 * あればそれを優先する）。
 * 得点の低いカード (unknown) は贈り物の画像が無い新しい贈り物かもしれず、
 * 最も近い贈り物とは別物のことが多いので、贈り物ごとにはまとめず unknowns に入れる
 * （同じ贈り物に近いものは 1 つにする。スクロールの重なりで 2 回写るため）。
 */
function _giftOcr_merge(results) {
    var known = {};
    results.forEach(function (res) {
        res.cells.forEach(function (c) {
            if (c.tier && !c.uncertain) known[c.gift] = c.tier;
        });
    });
    var seen = {}, unknowns = [], unknownSeen = {};
    results.forEach(function (res) {
        var votes = {}, inferred = null;
        res.cells.forEach(function (c) {
            if (!c.tier && !c.unknown && known[c.gift]) {
                votes[known[c.gift]] = (votes[known[c.gift]] || 0) + 1;
            }
        });
        Object.keys(votes).forEach(function (t) {
            if (!inferred || votes[t] > votes[inferred]) inferred = t;
        });
        res.cells.forEach(function (c) {
            var tier = c.tier || inferred;
            if (c.unknown) {
                if (!unknownSeen[c.gift]) {
                    unknownSeen[c.gift] = true;
                    unknowns.push({ gift: c.gift, tier: tier, crop: c.crop });
                }
                return;
            }
            (seen[c.gift] = seen[c.gift] || []).push({ tier: tier, uncertain: c.uncertain });
        });
    });
    var gifts = {}, conflicts = [];
    Object.keys(seen).forEach(function (id) {
        var cs = seen[id].filter(function (c) { return c.tier; });
        if (!cs.length) {
            gifts[id] = { tier: null, uncertain: true };
            return;
        }
        var sure = cs.filter(function (c) { return !c.uncertain; });
        var pool = sure.length ? sure : cs;
        var tiers = pool.map(function (c) { return c.tier; });
        var same = tiers.every(function (t) { return t === tiers[0]; });
        if (!same) conflicts.push(id);
        gifts[id] = { tier: tiers[0], uncertain: !sure.length || !same };
    });
    return { gifts: gifts, conflicts: conflicts, unknowns: unknowns };
}

/**
 * 読み取った段を present.tier（ラジオの値）にする。
 * favorite の段は高級の贈り物の基本の段なので、通常の贈り物だけ favorite にする。
 */
function _giftOcr_presentTier(tier, high) {
    if (tier === "ultra") return "ultraFavorite";
    if (tier === "super") return "superFavorite";
    if (tier === "favorite" && !high) return "favorite";
    return "";
}

/* ------------------------------------------------------------------ */
/*  ブラウザ（画像の読み込み・ページへの反映）                             */
/* ------------------------------------------------------------------ */

function _giftOcr_loadImage(src) {
    return new Promise(function (resolve, reject) {
        var im = new Image();
        im.onload = function () { resolve(im); };
        im.onerror = function () { reject(new Error("load failed: " + src)); };
        im.src = src;
    });
}

function _giftOcr_imageData(im) {
    var canvas = document.createElement("canvas");
    canvas.width = im.naturalWidth;
    canvas.height = im.naturalHeight;
    var ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(im, 0, 0);
    return ctx.getImageData(0, 0, canvas.width, canvas.height);
}

/** カードの切り抜き（data URL）。要確認の一覧に出す。 */
function _giftOcr_cropCard(im, rect) {
    var canvas = document.createElement("canvas");
    canvas.width = 96;
    canvas.height = Math.round(96 * rect.height / rect.width);
    canvas.getContext("2d").drawImage(im, rect.left, rect.top, rect.width, rect.height,
        0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.85);
}

var _giftOcr_refsPromise = null;

/**
 * 照合用データ（ページ内で 1 回だけ作る）。gifts は [{id, name, type, src}]。
 * Returns {refs: [{id, name, high, all, feature}], faceRefs: {tier: 特徴}}。
 */
function _giftOcr_loadRefs(gifts) {
    if (!_giftOcr_refsPromise) {
        var giftRefs = Promise.all(gifts.map(function (g) {
            return _giftOcr_loadImage(g.src).then(function (im) {
                return {
                    id: g.id, name: g.name,
                    high: g.type.indexOf("high") === 0,
                    all: /-all$/.test(g.type),
                    feature: _giftOcr_giftFeature(_giftOcr_imageData(im)),
                };
            }, function () { return null; });
        }));
        var faceRefs = Promise.all(_giftOcr_TIERS.map(function (t) {
            return _giftOcr_loadImage("/assets/reaction/" + t + ".png").then(function (im) {
                return _giftOcr_reactionFeature(_giftOcr_imageData(im));
            });
        }));
        _giftOcr_refsPromise = Promise.all([giftRefs, faceRefs]).then(function (r) {
            var faces = {};
            _giftOcr_TIERS.forEach(function (t, i) { faces[t] = r[1][i]; });
            return { refs: r[0].filter(Boolean), faceRefs: faces };
        });
    }
    return _giftOcr_refsPromise;
}

function _giftOcr_esc(s) {
    var d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
}

/**
 * ファイル選択欄 (input[type=file]) の画像を読み、ページの好みのラジオ
 * (name="g_<贈り物ID>") に入れる。box は結果を出す要素、gifts は贈り物の一覧
 * [{id, name, type, src}]（花束など好みのラジオが無い贈り物も含む）。
 */
async function giftOcrRead(input, box, gifts) {
    var files = Array.prototype.slice.call(input.files || []);
    if (!files.length) return;
    box.innerHTML = "読み取り中...";
    try {
        var data = await _giftOcr_loadRefs(gifts);
        var results = [], failed = 0, crops = {};
        for (var i = 0; i < files.length; i++) {
            var url = URL.createObjectURL(files[i]);
            try {
                var im = await _giftOcr_loadImage(url);
                var res = _giftOcr_readImage(_giftOcr_imageData(im), data.refs, data.faceRefs);
                if (!res.cells.length) failed++;
                res.cells.forEach(function (c) {
                    // 要確認の一覧に出す切り抜き（贈り物ごとに最初の 1 枚。
                    // 新しい贈り物かもしれないカードはカードごと）
                    if (c.unknown) {
                        c.crop = _giftOcr_cropCard(im, c.rect);
                    } else if (!crops[c.gift]) {
                        crops[c.gift] = _giftOcr_cropCard(im, c.rect);
                    }
                    delete c.rect;
                });
                results.push(res);
            } catch (e) {
                failed++;
            } finally {
                URL.revokeObjectURL(url);
            }
        }
        _giftOcr_apply(_giftOcr_merge(results), data.refs, crops, box, files.length, failed);
    } catch (e) {
        box.innerHTML = '<span class="error-text">読み取りに失敗しました。</span>';
    } finally {
        input.value = "";  // 同じ画像を選び直しても読み直せるように
    }
}

/** 読み取り結果をラジオに入れ、件数・要確認・未検出を box に出す。 */
function _giftOcr_apply(merged, refs, crops, box, images, failed) {
    var byId = {};
    refs.forEach(function (r) { byId[r.id] = r; });
    document.querySelectorAll(".gift-ocr-uncertain").forEach(function (el) {
        el.classList.remove("gift-ocr-uncertain");
    });
    function radioOf(id, value) {
        return document.querySelector('input[type=radio][name="g_' + CSS.escape(id)
            + '"][value="' + value + '"]');
    }
    var counts = { ultraFavorite: 0, superFavorite: 0, favorite: 0 };
    var unsure = [];
    Object.keys(merged.gifts).forEach(function (id) {
        var m = merged.gifts[id], ref = byId[id];
        if (m.uncertain) unsure.push(id);
        if (!m.tier) return;
        var value = _giftOcr_presentTier(m.tier, ref.high);
        var radio = radioOf(id, value);
        if (!radio) return;  // 好みのラジオが無い贈り物（花束など）
        radio.checked = true;
        radio.dispatchEvent(new Event("change", { bubbles: true }));
        if (value) counts[value]++;
        if (m.uncertain) {
            var row = radio.closest("tr, .gift-card");
            if (row) row.classList.add("gift-ocr-uncertain");
        }
    });
    // 件数・未検出は好みのラジオがある贈り物だけで数える
    // （花束などは好みを持たず、初音ミクのフォトカードはパネルに出ない）
    var editable = refs.filter(function (r) { return radioOf(r.id, ""); });
    var missing = editable.filter(function (r) { return !merged.gifts[r.id]; });

    var tierLabel = { ultra: "特大", super: "大", favorite: "中", normal: "普通" };
    var html = "<div>" + images + " 枚を読み取り、好みを選べる贈り物 "
        + (editable.length - missing.length) + " / " + editable.length
        + " 種類を見つけました（特大 " + counts.ultraFavorite
        + "・大 " + counts.superFavorite + "・中 " + counts.favorite + " を選択）。"
        + "見つけた贈り物の好みだけ入れ替えています。</div>";
    if (failed) {
        html += '<div class="error-text">' + failed + " 枚はパネルを見つけられませんでした。</div>";
    }
    function item(crop, text) {
        return '<div class="gift-ocr-item">' + (crop ? '<img src="' + crop + '" alt="">' : "")
            + "<span>" + text + "</span></div>";
    }
    function tierText(tier) {
        return tier ? "段: " + tierLabel[tier] : "段: 不明（見出しが写っていません）";
    }
    var unknowns = merged.unknowns;
    if (unsure.length || unknowns.length) {
        html += '<div class="error-text">要確認 ' + (unsure.length + unknowns.length)
            + " 件（橙色の枠の贈り物）。切り抜きと読み取り結果を見比べてください:</div>"
            + '<div class="gift-ocr-list">'
            + unsure.map(function (id) {
                return item(crops[id], _giftOcr_esc(byId[id].name) + "<br>"
                    + tierText(merged.gifts[id].tier));
            }).join("")
            // 似た別の贈り物の好みを書き換えないよう、ラジオには入れない
            + unknowns.map(function (u) {
                return item(u.crop, "贈り物の画像に無い贈り物かもしれません（入れていません）<br>"
                    + "近い贈り物: " + _giftOcr_esc(byId[u.gift].name) + "・" + tierText(u.tier));
            }).join("")
            + "</div>";
    }
    if (missing.length) {
        html += "<div>未検出 " + missing.length + " 件（好みは変えていません）: "
            + missing.map(function (r) { return _giftOcr_esc(r.name); }).join("、") + "</div>";
    }
    box.innerHTML = html;
}

if (typeof module !== "undefined") {
    module.exports = {
        findHeader: _giftOcr_findHeader,
        readImage: _giftOcr_readImage,
        merge: _giftOcr_merge,
        presentTier: _giftOcr_presentTier,
        giftFeature: _giftOcr_giftFeature,
        reactionFeature: _giftOcr_reactionFeature,
        assign: _giftOcr_assign,
        TIERS: _giftOcr_TIERS,
    };
}
