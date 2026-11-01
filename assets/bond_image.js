/**
 * 絆ランク管理: 現在の絆ランクの一覧を画像（PNG）で保存する。
 *
 * 絆ランクを設定済みの衣装を、絆ランク10刻み（100, 99〜90, 89〜80, …, 19〜10, 9〜1）の
 * グループに分けて高い順に並べ、生徒画像の右下に絆ランクを重ねて canvas に描く。
 * グループは左端に範囲を書き、1行 _BOND_IMAGE_COLS 人を超えたら折り返す。
 * Dash の clientside_callback として登録される（main.py）。
 */

var _BOND_IMAGE_COLS = 10;
var _BOND_IMAGE_SCALE = 2;  // 高解像度で描く倍率
// canvas の画素数の上限。iOS Safari は約1,670万画素を超える canvas を描けない
// （真っ白になる）ため、超えるときは倍率を下げる
var _BOND_IMAGE_MAX_PIXELS = 16000000;
var _BOND_IMAGE_CELL_W = 92;
var _BOND_IMAGE_CELL_H = 100;
var _BOND_IMAGE_ICON_W = 64;  // assets/student の画像の大きさ
var _BOND_IMAGE_ICON_H = 72;
var _BOND_IMAGE_PAD = 16;
var _BOND_IMAGE_TITLE_H = 40;
var _BOND_IMAGE_LABEL_W = 72;  // グループの範囲を書く左端の列
var _BOND_IMAGE_GROUP_GAP = 12;  // グループの間（区切り線を引く）
var _BOND_IMAGE_FONT = '"Hiragino Kaku Gothic ProN", "Hiragino Sans", Meiryo, sans-serif';

function _bondImage_loadIcon(label) {
    return new Promise(function (resolve) {
        var im = new Image();
        im.onload = function () { resolve(im); };
        im.onerror = function () { resolve(null); };
        im.src = "/assets/student/" + encodeURIComponent(label) + ".png";
    });
}

function _bondImage_roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
}

/** 幅 maxW に収まるよう、はみ出す文字を「…」にした text。 */
function _bondImage_fit(ctx, text, maxW) {
    if (ctx.measureText(text).width <= maxW) return text;
    var s = text;
    while (s.length > 1 && ctx.measureText(s + "…").width > maxW) s = s.slice(0, -1);
    return s + "…";
}

/**
 * 絆ランクの高い順の entries を10刻みのグループ [{top, bottom, entries}, ...] に分ける。
 * ぴったりの値（50 など）は上のグループに含める: 100, 99〜90, 89〜80, …, 19〜10, 9〜1。
 */
function _bondImage_groups(entries) {
    var groups = [];
    entries.forEach(function (e) {
        // 最高の100は単独のグループにする
        var bottom = Math.floor(e.rank / 10) * 10;
        var g = groups[groups.length - 1];
        if (!g || g.bottom !== bottom) {
            groups.push(g = {
                top: bottom === 100 ? 100 : bottom + 9,
                bottom: bottom,
                entries: [],
            });
        }
        g.entries.push(e);
    });
    return groups;
}

/**
 * 絆ランクの高い順の entries [{label, rank, icon}, ...]（icon は Image か null）を
 * 描いた canvas。
 */
function _bondImage_draw(entries) {
    var groups = _bondImage_groups(entries);
    var cols = Math.min(_BOND_IMAGE_COLS, Math.max.apply(null, groups.map(function (g) {
        return g.entries.length;
    })));
    var rows = 0;
    groups.forEach(function (g) { rows += Math.ceil(g.entries.length / _BOND_IMAGE_COLS); });
    var w = _BOND_IMAGE_PAD * 2 + _BOND_IMAGE_LABEL_W + cols * _BOND_IMAGE_CELL_W;
    var h = _BOND_IMAGE_PAD * 2 + _BOND_IMAGE_TITLE_H + rows * _BOND_IMAGE_CELL_H
        + (groups.length - 1) * _BOND_IMAGE_GROUP_GAP;
    var canvas = document.createElement("canvas");
    var scale = Math.min(_BOND_IMAGE_SCALE, Math.sqrt(_BOND_IMAGE_MAX_PIXELS / (w * h)));
    canvas.width = Math.floor(w * scale);
    canvas.height = Math.floor(h * scale);
    var ctx = canvas.getContext("2d");
    ctx.scale(scale, scale);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, w, h);

    // 見出し: 「絆ランク」・衣装数・日付
    var d = new Date();
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    ctx.fillStyle = "#333";
    ctx.font = "bold 18px " + _BOND_IMAGE_FONT;
    ctx.fillText("絆ランク", _BOND_IMAGE_PAD, _BOND_IMAGE_PAD + 14);
    ctx.textAlign = "right";
    ctx.fillStyle = "#888";
    ctx.font = "12px " + _BOND_IMAGE_FONT;
    ctx.fillText(
        entries.length + " 衣装・" + d.getFullYear() + "/" + (d.getMonth() + 1) + "/" + d.getDate(),
        w - _BOND_IMAGE_PAD, _BOND_IMAGE_PAD + 14
    );

    var gy = _BOND_IMAGE_PAD + _BOND_IMAGE_TITLE_H;
    groups.forEach(function (g, gi) {
        if (gi > 0) {
            // 前のグループとの区切り線
            var ly = gy - _BOND_IMAGE_GROUP_GAP / 2 - 2;
            ctx.strokeStyle = "#dde2e8";
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(_BOND_IMAGE_PAD, ly);
            ctx.lineTo(w - _BOND_IMAGE_PAD, ly);
            ctx.stroke();
        }
        // グループの範囲（例: 99〜90。100 は単独）
        ctx.textAlign = "left";
        ctx.fillStyle = "#555";
        ctx.font = "bold 14px " + _BOND_IMAGE_FONT;
        ctx.fillText(g.top === g.bottom ? String(g.top) : g.top + "〜" + Math.max(g.bottom, 1), _BOND_IMAGE_PAD, gy + _BOND_IMAGE_ICON_H / 2);
        g.entries.forEach(function (e, i) {
            _bondImage_drawCell(
                ctx, e,
                _BOND_IMAGE_PAD + _BOND_IMAGE_LABEL_W + (i % _BOND_IMAGE_COLS) * _BOND_IMAGE_CELL_W,
                gy + Math.floor(i / _BOND_IMAGE_COLS) * _BOND_IMAGE_CELL_H
            );
        });
        gy += Math.ceil(g.entries.length / _BOND_IMAGE_COLS) * _BOND_IMAGE_CELL_H + _BOND_IMAGE_GROUP_GAP;
    });
    return canvas;
}

/** 左上 (x0, y0) のセルに衣装 e の生徒画像・絆ランク・衣装名を描く。 */
function _bondImage_drawCell(ctx, e, x0, y0) {
    var ix = x0 + (_BOND_IMAGE_CELL_W - _BOND_IMAGE_ICON_W) / 2;
    var iy = y0;

    // 生徒画像（無い衣装は灰色の枠）
    ctx.save();
    _bondImage_roundRect(ctx, ix, iy, _BOND_IMAGE_ICON_W, _BOND_IMAGE_ICON_H, 6);
    ctx.clip();
    ctx.fillStyle = "#eef1f5";
    ctx.fillRect(ix, iy, _BOND_IMAGE_ICON_W, _BOND_IMAGE_ICON_H);
    if (e.icon) ctx.drawImage(e.icon, ix, iy, _BOND_IMAGE_ICON_W, _BOND_IMAGE_ICON_H);
    ctx.restore();

    // 絆ランク（画像の右下に重ねる）
    var text = String(e.rank);
    ctx.font = "bold 15px " + _BOND_IMAGE_FONT;
    var bw = Math.max(26, ctx.measureText(text).width + 10);
    var bh = 20;
    var bx = ix + _BOND_IMAGE_ICON_W - bw + 4;
    var by = iy + _BOND_IMAGE_ICON_H - bh + 4;
    _bondImage_roundRect(ctx, bx, by, bw, bh, 10);
    ctx.fillStyle = "#e8618c";
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = "#ffffff";
    ctx.stroke();
    ctx.fillStyle = "#ffffff";
    ctx.textAlign = "center";
    ctx.fillText(text, bx + bw / 2, by + bh / 2 + 1);

    // 衣装名
    ctx.font = "10px " + _BOND_IMAGE_FONT;
    ctx.fillStyle = "#333";
    ctx.fillText(
        _bondImage_fit(ctx, e.label, _BOND_IMAGE_CELL_W - 4),
        x0 + _BOND_IMAGE_CELL_W / 2, iy + _BOND_IMAGE_ICON_H + 14
    );
}

window.dash_clientside = window.dash_clientside || {};
window.dash_clientside.bond_image = {
    /**
     * 絆ランク管理の保存データ（bond-ranks）を画像にしてダウンロードさせる。
     * refs は bm-ocr-refs（[[衣装ID, 表示名, 生徒画像があるか], ...]、
     * 衣装の表示順）。Returns 結果のメッセージ（bm-image-feedback）。
     */
    save: async function (nClicks, bondRanks, refs) {
        if (!nClicks) return window.dash_clientside.no_update;
        var rankByCostume = {};
        ((bondRanks && bondRanks.costumes) || []).forEach(function (e) {
            if (e && Number.isInteger(e.rank) && !(e.costume_id in rankByCostume)) {
                rankByCostume[e.costume_id] = e.rank;
            }
        });
        var entries = [];
        (refs || []).forEach(function (r, order) {
            var rank = rankByCostume[r[0]];
            if (rank !== undefined) {
                entries.push({ label: r[1], rank: rank, hasIcon: r[2], order: order });
            }
        });
        if (!entries.length) return "絆ランクを設定した衣装がありません。";
        // 絆ランクの高い順（同じなら一覧の表示順）
        entries.sort(function (a, b) { return b.rank - a.rank || a.order - b.order; });
        await Promise.all(entries.map(function (e) {
            return (e.hasIcon ? _bondImage_loadIcon(e.label) : Promise.resolve(null))
                .then(function (im) { e.icon = im; });
        }));
        var link = document.createElement("a");
        link.download = "bond_ranks.png";
        link.href = _bondImage_draw(entries).toDataURL("image/png");
        link.click();
        return "";
    },
};
