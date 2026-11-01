/**
 * 絆ランクのスクリーンショット読み取り（絆ランク管理ページ）
 *
 * ゲームの「生徒リスト」画面のスクリーンショットから、各カードの
 * 衣装と絆ランクを読み取る。処理はすべてブラウザ内で行い、画像は
 * サーバーへ送らない。
 *   1. ランク帯のハート（ピンク）を目印にカードを見つける
 *   2. カードの立ち絵を生徒画像 (assets/student) と比べて衣装を決める
 *   3. ハートの右の白い数字を数字テンプレートと比べて絆ランクを読む
 *   4. カードの下の名前を、各衣装の名前をブラウザで描いた画像と比べて 2 を確かめる
 * 位置・大きさはすべてハートの幅を基準にした比なので、画面の解像度に依らない。
 *
 * 画像処理の関数は {data, width, height}（RGBA の ImageData 相当）だけを
 * 扱い、DOM に依存しない（Node でも動かせる）。
 */

/* ------------------------------------------------------------------ */
/*  定数（ハートの幅 = 1 とした比。1749x984 のスクリーンショットで計測）     */
/* ------------------------------------------------------------------ */

// 立ち絵の左上（ハートの左上から）と幅。高さは生徒画像と同じ縦横比 (64:72)。
var _bondOcr_ART_LEFT = -2.353;
var _bondOcr_ART_TOP = -6.735;
var _bondOcr_ART_WIDTH = 7.059;

// 照合に使う縮小サイズ。
var _bondOcr_MATCH_W = 32;
var _bondOcr_MATCH_H = 36;

// 数字の正規化サイズ。
var _bondOcr_GLYPH_W = 16;
var _bondOcr_GLYPH_H = 20;

// 衣装の判定を「要確認」にする閾値（平均二乗誤差、2位との比）。
var _bondOcr_MAX_DIST = 4000;
var _bondOcr_MIN_RATIO = 1.25;

// 数字を「要確認」にする閾値（テンプレートとの差、_bondOcr_classifyGlyph の margin）。
// margin は見本に無い端末のスクリーンショットで誤読したとき最大 0.10 だった。
// 27 枚の見本の数字 (479 文字) では最小 0.21。
var _bondOcr_MAX_GLYPH_DIFF = 0.25;
var _bondOcr_MIN_GLYPH_MARGIN = 0.2;

// 名前の照合。全角かっこの高さ（ハートの幅比）を基準に、高さ NAME_H 画素へ縮める。
var _bondOcr_PAREN_H = 0.787;
var _bondOcr_NAME_H = 16;
// 名前の見えている高さがこれ未満（一覧の下端のフェードで消えている）なら名前は使わない。
var _bondOcr_MIN_NAME_H = 0.55;
// これより広い名前は、ゲームが横に縮めて表示する（幅の違いを罰しない）。
var _bondOcr_MAX_NAME_W = 6.5;
// 名前の距離に足す、幅の比 (log) の重み。
var _bondOcr_NAME_WIDTH_W = 0.1;
// 名前の距離が最小の衣装からこの差までの衣装は「名前が合う」とみなす。
// 27 枚 310 カードで、正しい衣装の差は最大 0.0022（別のフォントで描いたとき）。
var _bondOcr_NAME_TOL = 0.008;

// 数字テンプレート（スマホ・MuMu・PC 版のスクリーンショット 27 枚の数字を _bondOcr_glyph で
// 正規化し、端末の種類ごとに平均してから平均したもの）。1 文字 16x20、"#" が白い画素。
var _bondOcr_DIGITS = {
    "0": [
        "......####......",
        "....#######.....",
        "...#########....",
        "..####...####...",
        "..####....###...",
        "..###......###..",
        ".####......###..",
        ".####......###..",
        ".####......###..",
        ".####......###..",
        ".####......###..",
        ".####......###..",
        ".####......###..",
        ".####......###..",
        ".####......###..",
        "..###.....###...",
        "..####....###...",
        "...####..####...",
        "...#########....",
        ".....######.....",
    ],
    "1": [
        "..........#.....",
        ".........###....",
        "........####....",
        ".......#####....",
        "....########....",
        "....########....",
        ".....#######....",
        ".........###....",
        ".........###....",
        ".........###....",
        ".........###....",
        ".........###....",
        ".........###....",
        ".........###....",
        ".........###....",
        ".........###....",
        ".........###....",
        ".........###....",
        ".........###....",
        ".........##.....",
    ],
    "2": [
        ".....#####......",
        "....########....",
        "...##########...",
        "..####....####..",
        "..###......###..",
        ".####......###..",
        ".####......###..",
        "..##.......###..",
        "...........###..",
        "..........####..",
        "........#####...",
        ".......#####....",
        ".....######.....",
        "....#####.......",
        "...#####........",
        "..#####.........",
        "..####..........",
        ".#####..........",
        ".#############..",
        ".#############..",
    ],
    "3": [
        "......####......",
        "....########....",
        "...##########...",
        "..#####..####...",
        "..###.....###...",
        "..###.....###...",
        "..##......###...",
        "..........###...",
        ".........####...",
        "......######....",
        "......######....",
        "........#####...",
        "..........####..",
        "...........###..",
        ".###.......###..",
        ".####......###..",
        ".####......###..",
        "..####...####...",
        "...##########...",
        "....#######.....",
    ],
    "4": [
        ".........##.....",
        "........####....",
        ".......#####....",
        ".......#####....",
        "......######....",
        "......##.###....",
        ".....##..###....",
        "....###..###....",
        "....###..###....",
        "...###...###....",
        "..###....###....",
        "..###....###....",
        ".###.....###....",
        ".#############..",
        ".#############..",
        "...##########...",
        ".........###....",
        ".........###....",
        ".........###....",
        ".........###....",
    ],
    "5": [
        "....##########..",
        "...###########..",
        "...###########..",
        "...###..........",
        "..###...........",
        "..###...........",
        "..###...........",
        "..########......",
        "..###########...",
        "..############..",
        "..###.....####..",
        "...#.......###..",
        "...........###..",
        "............##..",
        ".###.......###..",
        ".####......###..",
        ".####.....####..",
        "..#####..#####..",
        "...##########...",
        "....########....",
    ],
    "6": [
        ".......###......",
        ".....#######....",
        "....#########...",
        "...####...###...",
        "..####.....###..",
        "..###......###..",
        "..###...........",
        ".####..###......",
        ".###########....",
        ".############...",
        ".#####....####..",
        ".####......###..",
        ".####......###..",
        ".####......###..",
        ".####......###..",
        "..###......###..",
        "..###.....####..",
        "...####..####...",
        "...##########...",
        ".....######.....",
    ],
    "7": [
        "..############..",
        ".##############.",
        ".##############.",
        "...........###..",
        "..........####..",
        "..........###...",
        ".........###....",
        "........####....",
        "........###.....",
        ".......###......",
        ".......###......",
        "......####......",
        "......###.......",
        ".....####.......",
        ".....####.......",
        ".....###........",
        ".....###........",
        "....####........",
        "....####........",
        "....###.........",
    ],
    "8": [
        "......####......",
        "....########....",
        "...##########...",
        "..####...####...",
        "..###.....###...",
        "..###.....###...",
        "..###.....###...",
        "...###....###...",
        "...##########...",
        "....########....",
        "...##########...",
        "..####....####..",
        "..###......###..",
        ".####......###..",
        ".####......###..",
        ".####......###..",
        "..###.....####..",
        "..###########...",
        "...##########...",
        ".....######.....",
    ],
    "9": [
        ".....#####......",
        "...#########....",
        "...##########...",
        "..####....###...",
        "..###.....###...",
        ".####......###..",
        ".####......###..",
        ".####......###..",
        ".####......###..",
        "..###.....####..",
        "..#####..#####..",
        "...###########..",
        "....######.###..",
        "...........###..",
        "...........###..",
        "..###.....###...",
        "..###.....###...",
        "..####..#####...",
        "...#########....",
        "....######......",
    ],
};

/* ------------------------------------------------------------------ */
/*  画像処理                                                           */
/* ------------------------------------------------------------------ */

/** mask (Uint8Array) の 4 近傍連結成分の外接矩形と画素数。 */
function _bondOcr_components(mask, w, h, minSize) {
    var label = new Uint8Array(w * h);
    var stack = new Int32Array(w * h);
    var out = [];
    for (var i = 0; i < w * h; i++) {
        if (!mask[i] || label[i]) continue;
        var sp = 0;
        stack[sp++] = i;
        label[i] = 1;
        var size = 0, x0 = w, x1 = -1, y0 = h, y1 = -1;
        while (sp) {
            var p = stack[--sp];
            var x = p % w, y = (p - x) / w;
            size++;
            if (x < x0) x0 = x;
            if (x > x1) x1 = x;
            if (y < y0) y0 = y;
            if (y > y1) y1 = y;
            if (x > 0 && mask[p - 1] && !label[p - 1]) { label[p - 1] = 1; stack[sp++] = p - 1; }
            if (x < w - 1 && mask[p + 1] && !label[p + 1]) { label[p + 1] = 1; stack[sp++] = p + 1; }
            if (y > 0 && mask[p - w] && !label[p - w]) { label[p - w] = 1; stack[sp++] = p - w; }
            if (y < h - 1 && mask[p + w] && !label[p + w]) { label[p + w] = 1; stack[sp++] = p + w; }
        }
        if (size >= minSize) {
            out.push({ size: size, x0: x0, x1: x1, y0: y0, y1: y1 });
        }
    }
    return out;
}

/** (x0..x1, y0..y1) の平均輝度。 */
function _bondOcr_meanLuma(img, x0, y0, x1, y1) {
    var d = img.data, sum = 0, n = 0;
    x0 = Math.max(0, Math.round(x0)); x1 = Math.min(img.width - 1, Math.round(x1));
    y0 = Math.max(0, Math.round(y0)); y1 = Math.min(img.height - 1, Math.round(y1));
    for (var y = y0; y <= y1; y++) {
        for (var x = x0; x <= x1; x++) {
            var o = (y * img.width + x) * 4;
            sum += 0.299 * d[o] + 0.587 * d[o + 1] + 0.114 * d[o + 2];
            n++;
        }
    }
    return n ? sum / n : 255;
}

/**
 * ランク帯のハートを探す。Returns {hearts: [{x0, x1, y0, y1}], unit: ハートの幅}。
 *
 * ピンクの連結成分のうち、ハートの形（縦横比・充填率）で左側が暗い
 * （ランク帯の上にある）ものを候補とし、幅が中央値に近いものだけ残す。
 */
function _bondOcr_findHearts(img) {
    var w = img.width, h = img.height, d = img.data;
    var mask = new Uint8Array(w * h);
    for (var i = 0; i < w * h; i++) {
        var r = d[i * 4], g = d[i * 4 + 1], b = d[i * 4 + 2];
        mask[i] = r >= 225 && g >= 155 && g <= 215 && b >= 185 && b <= 240
            && r - g >= 35 ? 1 : 0;
    }
    var cands = _bondOcr_components(mask, w, h, 30).filter(function (c) {
        var cw = c.x1 - c.x0 + 1, ch = c.y1 - c.y0 + 1;
        var aspect = cw / ch, fill = c.size / (cw * ch);
        if (aspect < 1.1 || aspect > 1.4 || fill < 0.6 || fill > 0.8) return false;
        var cy = (c.y0 + c.y1) / 2;
        return _bondOcr_meanLuma(img, c.x0 - 0.4 * cw, cy - 0.1 * cw,
            c.x0 - 0.2 * cw, cy + 0.1 * cw) < 130;
    });
    if (!cands.length) return { hearts: [], unit: 0 };
    var widths = cands.map(function (c) { return c.x1 - c.x0 + 1; })
        .sort(function (a, b) { return a - b; });
    var unit = widths[(widths.length - 1) >> 1];
    var hearts = cands.filter(function (c) {
        return Math.abs(c.x1 - c.x0 + 1 - unit) <= 0.15 * unit;
    });
    hearts.sort(function (a, b) {
        return Math.abs(a.y0 - b.y0) > unit ? a.y0 - b.y0 : a.x0 - b.x0;
    });
    return { hearts: hearts, unit: unit };
}

/**
 * img の矩形 (left, top, width, height)（小数可）を ow x oh に縮小した
 * RGB（Float32Array, 長さ ow*oh*3）。各出力画素は対応する範囲の画素の平均。
 * 透過画素は白と合成する。
 */
function _bondOcr_resample(img, left, top, width, height, ow, oh) {
    var d = img.data, out = new Float32Array(ow * oh * 3);
    for (var oy = 0; oy < oh; oy++) {
        var sy0 = Math.max(0, Math.floor(top + oy * height / oh));
        var sy1 = Math.min(img.height, Math.max(sy0 + 1, Math.floor(top + (oy + 1) * height / oh)));
        for (var ox = 0; ox < ow; ox++) {
            var sx0 = Math.max(0, Math.floor(left + ox * width / ow));
            var sx1 = Math.min(img.width, Math.max(sx0 + 1, Math.floor(left + (ox + 1) * width / ow)));
            var r = 0, g = 0, b = 0, n = 0;
            for (var y = sy0; y < sy1; y++) {
                for (var x = sx0; x < sx1; x++) {
                    var o = (y * img.width + x) * 4, a = d[o + 3] / 255;
                    r += d[o] * a + 255 * (1 - a);
                    g += d[o + 1] * a + 255 * (1 - a);
                    b += d[o + 2] * a + 255 * (1 - a);
                    n++;
                }
            }
            var k = (oy * ow + ox) * 3;
            n = n || 1;
            out[k] = r / n; out[k + 1] = g / n; out[k + 2] = b / n;
        }
    }
    return out;
}

// 照合に使う画素（左上のピン・右下の武器アイコン・ランク帯を除く）。
var _bondOcr_MATCH_MASK = (function () {
    var idx = [];
    for (var y = 0; y < _bondOcr_MATCH_H; y++) {
        var fy = (y + 0.5) / _bondOcr_MATCH_H;
        if (fy >= 0.8) continue;
        for (var x = 0; x < _bondOcr_MATCH_W; x++) {
            var fx = (x + 0.5) / _bondOcr_MATCH_W;
            if (fx < 0.2 && fy < 0.2) continue;
            if (fx >= 0.78 && fy >= 0.64) continue;
            idx.push(y * _bondOcr_MATCH_W + x);
        }
    }
    return idx;
})();

/** 生徒画像（RGBA）を照合用に縮小する。 */
function _bondOcr_iconFeature(img) {
    return _bondOcr_resample(img, 0, 0, img.width, img.height,
        _bondOcr_MATCH_W, _bondOcr_MATCH_H);
}

function _bondOcr_distance(a, b) {
    var mask = _bondOcr_MATCH_MASK, sum = 0;
    for (var i = 0; i < mask.length; i++) {
        var k = mask[i] * 3;
        var dr = a[k] - b[k], dg = a[k + 1] - b[k + 1], db = a[k + 2] - b[k + 2];
        sum += dr * dr + dg * dg + db * db;
    }
    return sum / (mask.length * 3);
}

/** カードの立ち絵の矩形。画像からはみ出すカードは null。 */
function _bondOcr_artRect(img, heart, unit) {
    var width = _bondOcr_ART_WIDTH * unit;
    var rect = {
        left: heart.x0 + _bondOcr_ART_LEFT * unit,
        top: heart.y0 + _bondOcr_ART_TOP * unit,
        width: width,
        height: width * _bondOcr_MATCH_H / _bondOcr_MATCH_W,
    };
    var tol = 0.02 * width;
    if (rect.left < -tol || rect.top < -tol
        || rect.left + rect.width > img.width + tol
        || rect.top + rect.height > img.height + tol) {
        return null;
    }
    return rect;
}

/**
 * 立ち絵に最も近い生徒画像。refs は [{id, label, feature}]。
 * 位置ずれに備えて少しずらした切り出しも試し、最小の距離を使う。
 * Returns {ref, second: 2 位の生徒画像, dist, ratio}（ratio は 2 位の距離 / 1 位の距離）。
 */
function _bondOcr_matchArt(img, rect, refs) {
    var step = 0.025 * rect.width, crops = [];
    for (var dy = -1; dy <= 1; dy++) {
        for (var dx = -1; dx <= 1; dx++) {
            crops.push(_bondOcr_resample(img, rect.left + dx * step, rect.top + dy * step,
                rect.width, rect.height, _bondOcr_MATCH_W, _bondOcr_MATCH_H));
        }
    }
    var best = null, bestDist = Infinity, second = null, secondDist = Infinity;
    refs.forEach(function (ref) {
        var dist = Infinity;
        crops.forEach(function (c) { dist = Math.min(dist, _bondOcr_distance(c, ref.feature)); });
        if (dist < bestDist) {
            second = best;
            secondDist = bestDist;
            bestDist = dist;
            best = ref;
        } else if (dist < secondDist) {
            second = ref;
            secondDist = dist;
        }
    });
    return { ref: best, second: second, dist: bestDist, ratio: secondDist / Math.max(bestDist, 1) };
}

/** 画素の白さ (0〜1)。ランク帯の暗い色が 0、数字の白が 1。 */
function _bondOcr_whiteness(d, o) {
    var v = (Math.min(d[o], d[o + 1], d[o + 2]) - 80) / 140;
    return v < 0 ? 0 : v > 1 ? 1 : v;
}

/**
 * 数字の矩形 box を GLYPH_W x GLYPH_H にする（高さを揃え、横は中央寄せ）。
 * 各画素は対応する範囲の白さの平均 (0〜1)。
 */
function _bondOcr_glyph(img, box) {
    var gw = _bondOcr_GLYPH_W, gh = _bondOcr_GLYPH_H;
    var cw = box.x1 - box.x0 + 1, ch = box.y1 - box.y0 + 1;
    var w = Math.max(1, Math.min(gw, Math.round(cw * gh / ch)));
    var off = (gw - w) >> 1;
    var out = new Float32Array(gw * gh);
    for (var gy = 0; gy < gh; gy++) {
        var sy0 = box.y0 + Math.floor(gy * ch / gh);
        var sy1 = Math.max(sy0 + 1, box.y0 + Math.floor((gy + 1) * ch / gh));
        for (var gx = 0; gx < w; gx++) {
            var sx0 = box.x0 + Math.floor(gx * cw / w);
            var sx1 = Math.max(sx0 + 1, box.x0 + Math.floor((gx + 1) * cw / w));
            var sum = 0, n = 0;
            for (var y = sy0; y < sy1; y++) {
                for (var x = sx0; x < sx1; x++) {
                    sum += _bondOcr_whiteness(img.data, (y * img.width + x) * 4);
                    n++;
                }
            }
            out[gy * gw + off + gx] = sum / n;
        }
    }
    return out;
}

/** テンプレート rows を (dx, dy) ずらした 0/1（範囲外は 0）。 */
function _bondOcr_shifted(rows, dx, dy) {
    var gw = _bondOcr_GLYPH_W, gh = _bondOcr_GLYPH_H, out = new Uint8Array(gw * gh);
    for (var y = 0; y < gh; y++) {
        for (var x = 0; x < gw; x++) {
            var ty = y + dy, tx = x + dx;
            out[y * gw + x] = ty >= 0 && ty < gh && tx >= 0 && tx < gw && rows[ty][tx] === "#" ? 1 : 0;
        }
    }
    return out;
}

/** 数字ごとの、テンプレートを ±1 画素ずらした 0/1 の一覧（初回に作る）。 */
var _bondOcr_shiftedDigits = null;
function _bondOcr_digitVariants() {
    if (!_bondOcr_shiftedDigits) {
        _bondOcr_shiftedDigits = Object.keys(_bondOcr_DIGITS).map(function (digit) {
            var variants = [];
            for (var dy = -1; dy <= 1; dy++) {
                for (var dx = -1; dx <= 1; dx++) {
                    variants.push(_bondOcr_shifted(_bondOcr_DIGITS[digit], dx, dy));
                }
            }
            return { digit: digit, variants: variants };
        });
    }
    return _bondOcr_shiftedDigits;
}

/**
 * 数字をテンプレートと比べる。Returns {digit, diff, margin}。
 *
 * 1. 各数字のテンプレートを ±1 画素ずらした中で最も近いものとの差で上位 2 つを選ぶ
 *    （diff はその差の画素平均, 0〜1）。
 * 2. 上位 2 つのテンプレートが食い違う画素だけで比べ直して決める。5 と 6 の
 *    ように共通部分が多い数字は、全体の差だと切り出しのずれに埋もれるため。
 *    margin はその画素で白さがどちらに寄っているか (0〜1、0 は五分五分)。
 */
function _bondOcr_classifyGlyph(glyph) {
    var n = _bondOcr_GLYPH_W * _bondOcr_GLYPH_H;
    var ranked = _bondOcr_digitVariants().map(function (d) {
        var best = null, bestDiff = Infinity;
        d.variants.forEach(function (t) {
            var diff = 0;
            for (var i = 0; i < n; i++) diff += Math.abs(t[i] - glyph[i]);
            if (diff < bestDiff) { bestDiff = diff; best = t; }
        });
        return { digit: d.digit, diff: bestDiff, template: best };
    }).sort(function (a, b) { return a.diff - b.diff; });
    var a = ranked[0], b = ranked[1];
    var dA = 0, dB = 0, size = 0;
    for (var i = 0; i < n; i++) {
        if (a.template[i] === b.template[i]) continue;
        dA += Math.abs(a.template[i] - glyph[i]);
        dB += Math.abs(b.template[i] - glyph[i]);
        size++;
    }
    var win = dB < dA ? b : a;
    return {
        digit: win.digit,
        diff: win.diff / n,
        margin: size ? Math.abs(dA - dB) / size : 0,
    };
}

/**
 * 横に広すぎる（数字がつながった）矩形を、白い画素が最も少ない列で分ける。
 * mask は (mx, my) を左上とする幅 mw の白い画素の mask。
 */
function _bondOcr_splitWide(box, mask, mw, mx, my) {
    var cw = box.x1 - box.x0 + 1, ch = box.y1 - box.y0 + 1;
    if (cw <= 0.85 * ch) return [box];
    var cut = -1, least = Infinity;
    for (var x = box.x0 + Math.round(0.3 * cw); x <= box.x0 + Math.round(0.7 * cw); x++) {
        var on = 0;
        for (var y = box.y0; y <= box.y1; y++) on += mask[(y - my) * mw + x - mx];
        if (on < least) { least = on; cut = x; }
    }
    var left = { x0: box.x0, x1: cut - 1, y0: box.y0, y1: box.y1 };
    var right = { x0: cut + 1, x1: box.x1, y0: box.y0, y1: box.y1 };
    return _bondOcr_splitWide(left, mask, mw, mx, my)
        .concat(_bondOcr_splitWide(right, mask, mw, mx, my));
}

/** ハートの右にある数字の矩形（画像の座標、左から順）。 */
function _bondOcr_digitBoxes(img, heart, unit) {
    var x0 = heart.x1 + 1;
    var x1 = Math.min(img.width, Math.round(heart.x0 + 3.2 * unit));
    var y0 = Math.max(0, Math.round(heart.y0 - 0.4 * unit));
    var y1 = Math.min(img.height, Math.round(heart.y1 + 0.4 * unit));
    var mw = Math.max(0, x1 - x0), mh = Math.max(0, y1 - y0);
    var mask = new Uint8Array(mw * mh);
    for (var y = 0; y < mh; y++) {
        for (var x = 0; x < mw; x++) {
            mask[y * mw + x] = _bondOcr_whiteness(img.data, ((y + y0) * img.width + x + x0) * 4) > 0.5 ? 1 : 0;
        }
    }
    var hcy = (heart.y0 + heart.y1) / 2 - y0;
    var comps = _bondOcr_components(mask, mw, mh, Math.round(0.03 * unit * unit))
        .filter(function (c) {
            var ch = c.y1 - c.y0 + 1;
            return ch >= 0.55 * unit && ch <= 0.9 * unit
                && Math.abs((c.y0 + c.y1) / 2 - hcy) < 0.25 * unit;
        })
        .sort(function (a, b) { return a.x0 - b.x0; });
    // ハートの直後から続く数字だけ（間が空いたら終わり）。1 桁目がハートから
    // 離れているときは手前の数字を読み落としているので、読めなかったことにする。
    var boxes = [], prevRight = 0;
    for (var i = 0; i < comps.length; i++) {
        if (comps[i].x0 - prevRight > 0.6 * unit) break;
        boxes = boxes.concat(_bondOcr_splitWide(comps[i], mask, mw, 0, 0));
        prevRight = comps[i].x1;
    }
    return boxes.slice(0, 3).map(function (b) {
        return { x0: b.x0 + x0, x1: b.x1 + x0, y0: b.y0 + y0, y1: b.y1 + y0 };
    });
}

/**
 * 絆ランクの数字を読む。Returns {rank, uncertain}。読めなければ null。
 * どれかの数字がテンプレートと離れている、または 2 位の数字と紛らわしい
 * ときは uncertain。
 */
function _bondOcr_readRank(img, heart, unit) {
    var boxes = _bondOcr_digitBoxes(img, heart, unit);
    if (!boxes.length) return null;
    var text = "", uncertain = false;
    boxes.forEach(function (box) {
        var res = _bondOcr_classifyGlyph(_bondOcr_glyph(img, box));
        text += res.digit;
        if (res.diff > _bondOcr_MAX_GLYPH_DIFF || res.margin < _bondOcr_MIN_GLYPH_MARGIN) {
            uncertain = true;
        }
    });
    return { rank: parseInt(text, 10), uncertain: uncertain };
}

/* ------------------------------------------------------------------ */
/*  名前                                                               */
/* ------------------------------------------------------------------ */

/**
 * カードの下の名前の濃さ (0〜1) の mask {m, w, h}。名前が無ければ null。
 *
 * 一覧の下端ではフェードで文字が下ほど薄くなるので、行ごとに背景と最も濃い
 * 画素の差で正規化する。文字の上端（最初に濃さの差が大きい行）から全角
 * かっこの高さぶんだけを名前とみなし、その下の区切りの点線は含めない。
 * 黄色い下線を拾わないよう、明るさは RGB の最大値で測る。
 */
function _bondOcr_nameMask(img, heart, unit, art) {
    var x0 = Math.max(0, Math.round(art.left - 0.6 * unit));
    var x1 = Math.min(img.width, Math.round(art.left + art.width + 0.6 * unit));
    var y0 = Math.round(heart.y1 + 0.6 * unit);
    var y1 = Math.min(img.height, Math.round(heart.y1 + 2.4 * unit));
    var w = x1 - x0, h = y1 - y0, d = img.data;
    if (w <= 0 || h <= 0) return null;
    var rows = [], top = -1;
    for (var y = 0; y < h; y++) {
        var row = new Float32Array(w);
        for (var x = 0; x < w; x++) {
            var o = ((y + y0) * img.width + x + x0) * 4;
            row[x] = Math.max(d[o], d[o + 1], d[o + 2]);
        }
        var sorted = Array.prototype.slice.call(row).sort(function (a, b) { return a - b; });
        var bg = sorted[Math.floor(0.7 * w)];
        rows.push({ v: row, bg: bg, c: bg - sorted[Math.floor(0.01 * w)] });
        if (top < 0 && rows[y].c >= 40) top = y;
    }
    if (top < 0) return null;
    var m = new Float32Array(w * h);
    var bottom = Math.min(h, top + Math.round(1.08 * _bondOcr_PAREN_H * unit));
    for (var y = top; y < bottom; y++) {
        var r = rows[y];
        if (r.c < 8) continue;
        for (var x = 0; x < w; x++) {
            var v = ((r.bg - r.v[x]) / r.c - 0.25) / 0.5;
            m[y * w + x] = v < 0 ? 0 : v > 1 ? 1 : v;
        }
    }
    _bondOcr_eraseDashes(m, w, h, unit);
    return { m: m, w: w, h: h };
}

/** 区切りの点線（小さな横長の点が同じ高さに 6 個以上並んだもの）を mask から消す。 */
function _bondOcr_eraseDashes(m, w, h, unit) {
    var bin = new Uint8Array(w * h);
    for (var i = 0; i < w * h; i++) bin[i] = m[i] > 0.5 ? 1 : 0;
    var dots = _bondOcr_components(bin, w, h, 1).filter(function (c) {
        var cw = c.x1 - c.x0 + 1, ch = c.y1 - c.y0 + 1;
        return ch <= 0.08 * unit && cw <= 0.3 * unit && cw >= ch;
    });
    dots.forEach(function (a) {
        var cy = (a.y0 + a.y1) / 2;
        var same = dots.filter(function (b) { return Math.abs((b.y0 + b.y1) / 2 - cy) <= 0.04 * unit; });
        if (same.length < 6) return;
        for (var y = a.y0; y <= a.y1; y++) {
            for (var x = a.x0; x <= a.x1; x++) m[y * w + x] = 0;
        }
    });
}

/**
 * mask の中央の文字のまとまりの矩形。隣のカードの名前のはみ出しは除く
 * （全角かっこの前後の空きより広い間隔で区切る）。文字が無ければ null。
 */
function _bondOcr_textBox(g, gap) {
    var ink = new Uint8Array(g.w), runs = [], start = -1, last = -Infinity;
    for (var x = 0; x < g.w; x++) {
        for (var y = 0; y < g.h; y++) {
            if (g.m[y * g.w + x] > 0.5) { ink[x] = 1; break; }
        }
        if (!ink[x]) continue;
        if (start < 0 || x - last > gap) {
            if (start >= 0) runs.push([start, last]);
            start = x;
        }
        last = x;
    }
    if (start >= 0) runs.push([start, last]);
    if (!runs.length) return null;
    var c = g.w / 2, run = null, best = Infinity;
    runs.forEach(function (r) {
        var dist = r[0] <= c && c <= r[1] ? 0 : Math.min(Math.abs(r[0] - c), Math.abs(r[1] - c));
        if (dist < best) { best = dist; run = r; }
    });
    var y0 = g.h, y1 = -1;
    for (var y = 0; y < g.h; y++) {
        for (var x = run[0]; x <= run[1]; x++) {
            if (g.m[y * g.w + x] > 0.5) { y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
        }
    }
    return { x0: run[0], x1: run[1], y0: y0, y1: y1 };
}

/** mask の (left, top, width, height) を ow x oh に縮め、3x3 でぼかした Float32Array。 */
function _bondOcr_nameFeature(g, left, top, width, height, ow, oh) {
    var a = new Float32Array(ow * oh), out = new Float32Array(ow * oh);
    for (var y = 0; y < oh; y++) {
        var sy0 = top + Math.floor(y * height / oh);
        var sy1 = Math.max(sy0 + 1, top + Math.floor((y + 1) * height / oh));
        for (var x = 0; x < ow; x++) {
            var sx0 = left + Math.floor(x * width / ow);
            var sx1 = Math.max(sx0 + 1, left + Math.floor((x + 1) * width / ow));
            var sum = 0, n = 0;
            for (var yy = sy0; yy < sy1; yy++) {
                for (var xx = sx0; xx < sx1; xx++) {
                    if (yy < g.h && xx < g.w) sum += g.m[yy * g.w + xx];
                    n++;
                }
            }
            a[y * ow + x] = sum / n;
        }
    }
    for (var y = 0; y < oh; y++) {
        for (var x = 0; x < ow; x++) {
            var sum = 0, n = 0;
            for (var dy = -1; dy <= 1; dy++) {
                for (var dx = -1; dx <= 1; dx++) {
                    var yy = y + dy, xx = x + dx;
                    if (yy >= 0 && yy < oh && xx >= 0 && xx < ow) { sum += a[yy * ow + xx]; n++; }
                }
            }
            out[y * ow + x] = sum / n;
        }
    }
    return { a: out, w: ow, h: oh };
}

/**
 * カードの名前の特徴 {a, w, h, maxed: ゲームが横に縮めた幅か}。
 * 名前が無い・フェードで見えない・切り出し範囲からはみ出しているときは null。
 */
function _bondOcr_readName(img, heart, unit, art) {
    var g = _bondOcr_nameMask(img, heart, unit, art);
    var box = g && _bondOcr_textBox(g, 0.9 * unit);
    if (!box || box.y1 - box.y0 + 1 < _bondOcr_MIN_NAME_H * unit
        || box.x0 <= 1 || box.x1 >= g.w - 2) {
        return null;
    }
    var k = _bondOcr_NAME_H / (_bondOcr_PAREN_H * unit);
    var bw = box.x1 - box.x0 + 1, bh = box.y1 - box.y0 + 1;
    var f = _bondOcr_nameFeature(g, box.x0, box.y0, bw, bh,
        Math.max(4, Math.round(bw * k)), Math.max(4, Math.round(bh * k)));
    f.maxed = bw >= _bondOcr_MAX_NAME_W * unit;
    return f;
}

/**
 * 描いた名前 {g: mask, box, parenH: 全角かっこの高さ} の、上端から oh 行ぶん
 * （カードの名前の見えている高さに合わせる）の特徴。
 */
function _bondOcr_renderedFeature(r, oh) {
    var k = _bondOcr_NAME_H / r.parenH, bw = r.box.x1 - r.box.x0 + 1;
    return _bondOcr_nameFeature(r.g, r.box.x0, r.box.y0, bw, oh / k,
        Math.max(4, Math.round(bw * k)), oh);
}

/**
 * 名前の特徴どうしの距離（列を伸縮して揃える DTW。フォントによる文字幅・
 * かっこの間隔の違いを吸収する）に、幅の比の罰を足したもの。
 */
function _bondOcr_nameDistance(p, q) {
    var n = p.w, m = q.w, h = p.h;
    var prev = new Float64Array(m + 1).fill(Infinity), cur = new Float64Array(m + 1);
    var band = Math.max(3, Math.round(0.3 * Math.max(n, m)));
    prev[0] = 0;
    for (var i = 1; i <= n; i++) {
        cur.fill(Infinity);
        var jc = Math.round(i * m / n);
        for (var j = Math.max(1, jc - band); j <= Math.min(m, jc + band); j++) {
            var d = 0;
            for (var y = 0; y < h; y++) d += Math.abs(p.a[y * n + i - 1] - q.a[y * m + j - 1]);
            cur[j] = d + Math.min(prev[j - 1], prev[j], cur[j - 1]);
        }
        var t = prev; prev = cur; cur = t;
    }
    var ratio = Math.log(n / m);
    if (ratio < 0 && p.maxed) ratio = 0;
    return prev[m] / ((n + m) * h) + _bondOcr_NAME_WIDTH_W * Math.abs(ratio);
}

/**
 * 名前の距離 {衣装ID: 距離} と最小の衣装。names は [{id, label, rendered}]。
 * 同じ高さの描いた名前の特徴は cache に作り置きする。
 */
function _bondOcr_nameDistances(name, names, cache) {
    var feats = cache[name.h];
    if (!feats) {
        feats = cache[name.h] = names.map(function (n) {
            return _bondOcr_renderedFeature(n.rendered, name.h);
        });
    }
    var dist = {}, best = null;
    names.forEach(function (n, i) {
        dist[n.id] = _bondOcr_nameDistance(name, feats[i]);
        if (!best || dist[n.id] < dist[best.id]) best = n;
    });
    return { dist: dist, best: best };
}

/**
 * 立ち絵の照合結果 m と名前の距離 nd から衣装を決める。
 * Returns {id, label, uncertain, name: 食い違ったときの読み取った名前}。
 *   - 名前が立ち絵の 1 位と合う: 1 位。立ち絵で迷っても、名前が 2 位と
 *     区別できれば確実とする
 *   - 立ち絵で迷い、名前が 2 位と合う: 2 位
 *   - 名前が生徒画像の無い衣装と合う: その衣装（要確認）
 *   - それ以外: 立ち絵の 1 位のまま要確認（候補に無い衣装の取り違えなど）
 */
function _bondOcr_decide(m, artUncertain, nd) {
    var pick = { id: m.ref.id, label: m.ref.label, uncertain: artUncertain };
    if (!nd) return pick;
    var best = nd.dist[nd.best.id];
    var fits = function (ref) { return ref && nd.dist[ref.id] - best <= _bondOcr_NAME_TOL; };
    var apart = function (a, b) {
        return !b || nd.dist[b.id] - nd.dist[a.id] > _bondOcr_NAME_TOL;
    };
    if (fits(m.ref)) {
        pick.uncertain = artUncertain && !apart(m.ref, m.second);
    } else if (artUncertain && fits(m.second) && apart(m.second, m.ref)) {
        pick = { id: m.second.id, label: m.second.label, uncertain: false };
    } else if (!nd.best.hasIcon) {
        pick = { id: nd.best.id, label: nd.best.label, uncertain: true };
    } else {
        pick.uncertain = true;
        pick.name = nd.best.label;
    }
    return pick;
}

/**
 * スクリーンショット 1 枚を読む。refs は生徒画像 [{id, label, feature}]、
 * names は名前 [{id, label, hasIcon, rendered}]（空なら名前は使わない）。
 * Returns {cards: [{costume_id, label, rank, uncertain, name?, rect: 立ち絵の矩形}],
 * partial: はみ出して読まなかったカード数}。
 */
function _bondOcr_readImage(img, refs, names) {
    var found = _bondOcr_findHearts(img), cards = [], partial = 0, cache = {};
    found.hearts.forEach(function (heart) {
        var rect = _bondOcr_artRect(img, heart, found.unit);
        if (!rect) { partial++; return; }
        var m = _bondOcr_matchArt(img, rect, refs);
        var r = _bondOcr_readRank(img, heart, found.unit);
        if (!m.ref) return;
        var name = names && names.length && _bondOcr_readName(img, heart, found.unit, rect);
        var pick = _bondOcr_decide(m,
            m.dist > _bondOcr_MAX_DIST || m.ratio < _bondOcr_MIN_RATIO,
            name ? _bondOcr_nameDistances(name, names, cache) : null);
        var card = {
            costume_id: pick.id,
            label: pick.label,
            rank: r && r.rank >= 1 ? r.rank : null,
            uncertain: pick.uncertain || !r || r.uncertain,
            rect: rect,
        };
        if (pick.name) card.name = pick.name;
        cards.push(card);
    });
    return { cards: cards, partial: partial };
}

/* ------------------------------------------------------------------ */
/*  ブラウザ（画像の読み込み）                                          */
/* ------------------------------------------------------------------ */

function _bondOcr_loadImage(src) {
    return new Promise(function (resolve, reject) {
        var im = new Image();
        im.onload = function () { resolve(im); };
        im.onerror = function () { reject(new Error("load failed: " + src)); };
        im.src = src;
    });
}

function _bondOcr_imageData(im) {
    var canvas = document.createElement("canvas");
    canvas.width = im.naturalWidth;
    canvas.height = im.naturalHeight;
    var ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(im, 0, 0);
    return ctx.getImageData(0, 0, canvas.width, canvas.height);
}

// 確認表に出すカードの切り抜きの高さ (px)。表示はその半分（高解像度の画面向け）。
var _bondOcr_CROP_H = 280;

/**
 * カードの切り抜き（JPEG の data URL）。立ち絵の矩形はランク帯の数字まで含む。
 */
function _bondOcr_cropCard(im, rect) {
    var canvas = document.createElement("canvas");
    canvas.height = _bondOcr_CROP_H;
    canvas.width = Math.round(_bondOcr_CROP_H * rect.width / rect.height);
    canvas.getContext("2d").drawImage(im, rect.left, rect.top, rect.width, rect.height,
        0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.85);
}

// 名前を描くフォント（端末に入っている日本語フォント）。
var _bondOcr_NAME_FONT = '500 40px "Hiragino Sans", "Hiragino Kaku Gothic ProN", '
    + '"Yu Gothic", Meiryo, "Noto Sans JP", "Noto Sans CJK JP", sans-serif';

/** text を描いた濃さの mask と文字の矩形 {g, box}。 */
function _bondOcr_renderText(text) {
    var canvas = document.createElement("canvas");
    canvas.width = 800;
    canvas.height = 80;
    var ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#000";
    ctx.font = _bondOcr_NAME_FONT;
    ctx.textBaseline = "middle";
    ctx.fillText(text, 4, canvas.height / 2);
    var d = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    var g = { m: new Float32Array(canvas.width * canvas.height), w: canvas.width, h: canvas.height };
    for (var i = 0; i < g.m.length; i++) g.m[i] = 1 - d[i * 4] / 255;
    return { g: g, box: _bondOcr_textBox(g, Infinity) };
}

// 照合用データ（ページ内で 1 回だけ作る）。
var _bondOcr_refsPromise = null;

/**
 * refs: [[costume_id, 表示名, 生徒画像があるか], ...]。
 * Returns {icons: 生徒画像 [{id, label, feature}], names: 名前 [{id, label, hasIcon, rendered}]}。
 * 画像を読み込めなかった衣装は名前だけで照合する。
 */
function _bondOcr_loadRefs(refs) {
    if (!refs.length) return Promise.resolve({ icons: [], names: [] });  // 一覧の描画前（作り置きしない）
    if (!_bondOcr_refsPromise) {
        _bondOcr_refsPromise = Promise.all(refs.map(function (r) {
            if (!r[2]) return null;
            return _bondOcr_loadImage("/assets/student/" + encodeURIComponent(r[1]) + ".png")
                .then(function (im) {
                    return { id: r[0], label: r[1], feature: _bondOcr_iconFeature(_bondOcr_imageData(im)) };
                }, function () { return null; });
        })).then(function (icons) {
            var parenH = _bondOcr_renderText("（").box;
            parenH = parenH.y1 - parenH.y0 + 1;
            var names = refs.map(function (r, i) {
                var rendered = _bondOcr_renderText(r[1]);
                if (!rendered.box) return null;
                rendered.parenH = parenH;
                return { id: r[0], label: r[1], hasIcon: !!icons[i], rendered: rendered };
            });
            return { icons: icons.filter(Boolean), names: names.filter(Boolean) };
        });
    }
    return _bondOcr_refsPromise;
}

/* ------------------------------------------------------------------ */
/*  Dash clientside_callback 登録                                      */
/* ------------------------------------------------------------------ */

window.dash_clientside = window.dash_clientside || {};
window.dash_clientside.bond_ocr = {
    /**
     * dcc.Upload の contents（data URL のリスト）を読み、bm-ocr-result に
     * {cards, images, failed, partial, error?} を返す。読み終えたら contents を
     * 空にする（同じ画像を選び直しても読み直せるように）。
     *
     * カードの切り抜きは bm-ocr-crops に {衣装ID: {ok: [data URL, ...], mismatch: [...]}}
     * （mismatch は名前が衣装と食い違ったカード）で入れる。bm-ocr-result は
     * サーバーのコールバックへ送られるので、画像は入れない。
     */
    read: async function (contents, refs) {
        var dc = window.dash_clientside;
        if (!contents || !contents.length) return dc.no_update;
        dc.set_props("bm-ocr-status", { children: "読み取り中..." });
        var result = { cards: [], images: contents.length, failed: 0, partial: 0 };
        var crops = {};
        try {
            var refData = await _bondOcr_loadRefs(refs || []);
            for (var i = 0; i < contents.length; i++) {
                try {
                    var im = await _bondOcr_loadImage(contents[i]);
                    var res = _bondOcr_readImage(_bondOcr_imageData(im), refData.icons, refData.names);
                    if (!res.cards.length) result.failed++;
                    result.partial += res.partial;
                    res.cards.forEach(function (c) {
                        var cc = crops[c.costume_id] = crops[c.costume_id] || { ok: [], mismatch: [] };
                        cc[c.name ? "mismatch" : "ok"].push(_bondOcr_cropCard(im, c.rect));
                        delete c.rect;
                    });
                    result.cards = result.cards.concat(res.cards);
                } catch (e) {
                    result.failed++;
                }
            }
        } catch (e) {
            result.error = true;
        } finally {
            dc.set_props("bm-ocr-upload", { contents: null });
        }
        dc.set_props("bm-ocr-crops", { data: crops });
        return result;
    },

    /**
     * 確認表の衣装の行に、その衣装と判定したカードの切り抜きを並べる
     * （スクロールの重なりで複数回読んだ衣装は複数枚）。名前が合うカードが
     * あれば、名前が食い違ったカードは出さない（merge_ocr_cards と同じ）。
     */
    crops: function (id, crops) {
        var cc = (crops || {})[id.costume] || { ok: [], mismatch: [] };
        return (cc.ok.length ? cc.ok : cc.mismatch).map(function (src) {
            return {
                type: "Img",
                namespace: "dash_html_components",
                props: { src: src, alt: "読み取ったカード", className: "bm-ocr-crop" },
            };
        });
    },
};

if (typeof module !== "undefined") {
    module.exports = {
        readImage: _bondOcr_readImage,
        iconFeature: _bondOcr_iconFeature,
        findHearts: _bondOcr_findHearts,
        digitBoxes: _bondOcr_digitBoxes,
        glyph: _bondOcr_glyph,
        classifyGlyph: _bondOcr_classifyGlyph,
        matchArt: _bondOcr_matchArt,
        artRect: _bondOcr_artRect,
        readName: _bondOcr_readName,
        nameDistances: _bondOcr_nameDistances,
        decide: _bondOcr_decide,
        DIGITS: _bondOcr_DIGITS,
    };
}
