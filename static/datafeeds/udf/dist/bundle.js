!(function (t, e) {
    "object" == typeof exports && "undefined" != typeof module
        ? (module.exports = e())
        : "function" == typeof define && define.amd
        ? define(e)
        : ((t = "undefined" != typeof globalThis ? globalThis : t || self).Datafeeds =
              t.Datafeeds || {},
          (t.Datafeeds.UDFCompatibleDatafeed = e()));
})(this, function () {
    "use strict";
    function t(t) {
        return (t = t.toString()).length >= 2 ? t : "0" + t;
    }
    var e = (function () {
        function t(t, e) {
            (this._datafeedURL = t),
                (this._updateFrequency = void 0 !== e ? e : 1e4),
                (this._lastBarCache = new Map()),
                (this._subscribers = new Map()),
                (this._requestId = 0),
                (this._requestsPending = new Map());
        }
        return (
            (t.prototype.onReady = function (t) {
                var e = this;
                this._send(
                    "/config",
                    {},
                    function (s) {
                        t({
                            supports_search: s.supports_search,
                            supports_group_request: s.supports_group_request,
                            supported_resolutions: s.supported_resolutions,
                            supports_marks: s.supports_marks,
                            supports_timescale_marks: s.supports_timescale_marks,
                            supports_time: s.supports_time,
                        });
                    },
                    function () {
                        t({});
                    }
                );
            }),
            (t.prototype.searchSymbols = function (t, e, s, i, n) {
                this._send(
                    "/search",
                    {
                        query: t,
                        type: e,
                        exchange: s,
                        limit: i,
                    },
                    function (t) {
                        n(t.result || []);
                    },
                    function () {
                        n([]);
                    }
                );
            }),
            (t.prototype.resolveSymbol = function (t, e) {
                var s = this;
                this._send(
                    "/symbols",
                    { symbol: t },
                    function (i) {
                        if (!i || i.error)
                            return void e("unknown_symbol");
                        var n = {
                            name: i.name,
                            ticker: i.ticker || t,
                            description: i.description || "",
                            type: i.type || "",
                            session: i.session || "24x7",
                            timezone: i.timezone || "UTC",
                            exchange: i.exchange || "",
                            listed_exchange: i.listed_exchange || i.exchange || "",
                            minmov: i.minmov || 1,
                            minmov2: i.minmov2 || 0,
                            pricescale: i.pricescale || 1,
                            pointvalue: i.pointvalue || 1,
                            has_intraday: i.has_intraday || !1,
                            has_no_volume: void 0 === i.has_no_volume || i.has_no_volume,
                            has_weekly_and_monthly:
                                i.has_weekly_and_monthly || !1,
                            has_daily: i.has_daily || !1,
                            supported_resolutions: i.supported_resolutions || [],
                            volume_precision: i.volume_precision || 0,
                            data_status: i.data_status || "streaming",
                        };
                        e(null, n);
                    },
                    function () {
                        e("unknown_symbol");
                    }
                );
            }),
            (t.prototype.getBars = function (t, e, s, i, n, o, r) {
                var a = this,
                    u = this._getURLForRequest(
                        "/history",
                        t,
                        e,
                        s,
                        i,
                        n,
                        o
                    );
                if (this._requestsPending.has(u))
                    return void (this._requestsPending.get(u).push({
                        callback: r,
                        meta: o,
                    }));
                var d = [];
                (this._requestsPending.set(u, d)),
                    d.push({ callback: r, meta: o });
                var l = ++this._requestId;
                this._send(
                    "/history",
                    {
                        symbol: t,
                        resolution: e,
                        from: s,
                        to: i,
                        countback: n,
                        firstDataRequest: o.firstDataRequest,
                    },
                    function (t) {
                        if (a._requestsPending.has(u)) {
                            var e = a._requestsPending.get(u);
                            a._requestsPending.delete(u);
                            var s = t.s === "ok" ? void 0 : t.err || "unknown_error";
                            if (s)
                                return void e.forEach(function (t) {
                                    t.callback(s, null);
                                });
                            var i = [],
                                n = t.t.length;
                            for (var o = 0; o < n; o++) {
                                var r = t.t[o],
                                    d = {
                                        time: 1e3 * r,
                                        open: t.o[o],
                                        high: t.h[o],
                                        low: t.l[o],
                                        close: t.c[o],
                                        volume: t.v[o],
                                    };
                                i.push(d);
                            }
                            a._lastBarCache.set(t + e, i[i.length - 1]),
                                e.forEach(function (e) {
                                    e.callback(null, i, {
                                        noData: 0 === i.length,
                                        nextTime: t.nb ? 1e3 * t.nb : void 0,
                                    });
                                });
                        }
                    },
                    function () {
                        a._requestsPending.delete(u),
                            d.forEach(function (t) {
                                t.callback("network_error", null);
                            });
                    }
                );
            }),
            (t.prototype.subscribeBars = function (t, e, s, i) {
                var n = t + "_" + e;
                this._subscribers.set(n, {
                    lastBarTime: null,
                    listener: i,
                    resolution: e,
                    symbol: t,
                    updateFrequency: this._updateFrequency,
                }),
                    this._startPeriodicUpdates(n);
            }),
            (t.prototype.unsubscribeBars = function (t, e) {
                var s = t + "_" + e;
                this._subscribers.delete(s);
            }),
            (t.prototype.getServerTime = function (t) {
                this._send(
                    "/time",
                    {},
                    function (e) {
                        t(1e3 * parseInt(e, 10));
                    },
                    function () {}
                );
            }),
            (t.prototype._send = function (t, e, s, i) {
                var n = this._datafeedURL + t,
                    o = [];
                for (var r in e) e.hasOwnProperty(r) && o.push(r + "=" + encodeURIComponent(e[r]));
                o.length > 0 && (n += "?" + o.join("&"));
                var a = new XMLHttpRequest();
                (a.open("GET", n, !0),
                (a.onreadystatechange = function () {
                    if (4 === a.readyState)
                        if (200 === a.status) {
                            try {
                                var t = JSON.parse(a.responseText);
                                s(t);
                            } catch (t) {
                                i();
                            }
                        } else i();
                }),
                (a.onerror = function () {
                    i();
                }),
                a.send(null));
            }),
            (t.prototype._getURLForRequest = function (t, e, s, i, n, o, r) {
                var a = this._datafeedURL + t,
                    u = [
                        "symbol=" + encodeURIComponent(e),
                        "resolution=" + encodeURIComponent(s),
                        "from=" + i,
                        "to=" + n,
                    ];
                return (
                    o && u.push("countback=" + o),
                    r.firstDataRequest && u.push("firstDataRequest=true"),
                    a + "?" + u.join("&")
                );
            }),
            (t.prototype._startPeriodicUpdates = function (t) {
                var e = this;
                this._subscribers.has(t) &&
                    (function t() {
                        if (e._subscribers.has(t)) {
                            var s = e._subscribers.get(t);
                            e._updateData(s),
                                (s.timerId = setTimeout(t, s.updateFrequency));
                        }
                    })();
            }),
            (t.prototype._updateData = function (t) {
                var e = this,
                    s = t.symbol,
                    i = t.resolution,
                    n = s + i,
                    o = Math.floor(Date.now() / 1e3),
                    r = this._lastBarCache.get(n);
                r && (o -= o % this._getResolutionSeconds(i)),
                    this.getBars(
                        s,
                        i,
                        r.time / 1e3 + 1,
                        o,
                        1000,
                        { firstDataRequest: !1 },
                        function (o, a, u) {
                            if (!o && a && a.length > 0) {
                                var d = a[a.length - 1];
                                e._lastBarCache.set(n, d);
                                var l = t.lastBarTime;
                                if (null !== l)
                                    for (var c = 0; c < a.length; c++) {
                                        var h = a[c];
                                        h.time > l && t.listener(h);
                                    }
                                t.lastBarTime = d.time;
                            }
                        }
                    );
            }),
            (t.prototype._getResolutionSeconds = function (t) {
                var e = t.toLowerCase();
                if (e.includes("d")) return 86400;
                if (e.includes("w")) return 604800;
                if (e.includes("m")) return 2592000;
                var s = parseInt(e, 10);
                return isNaN(s) ? 300 : 60 * s;
            }),
            t
        );
    })();
    return e;
});