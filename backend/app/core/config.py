"""Application configuration loaded from environment variables.

All settings are validated by Pydantic at startup; invalid config fails fast
rather than crashing later in a request path.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────
    APP_NAME: str = "StockEx"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    APP_DEBUG: bool = False
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_BASE_URL: str = "http://localhost:8000"

    # ── MongoDB ──────────────────────────────────────────────────────
    MONGODB_URL: str = "mongodb://localhost:27017/nexbrokers"
    MONGODB_DB_NAME: str = "nexbrokers"
    MONGODB_REPLICA_SET: str = ""
    MONGODB_MAX_POOL_SIZE: int = 100
    MONGODB_MIN_POOL_SIZE: int = 10

    # ── Risk-loop sharding (horizontal scale of SL/TP/stop-out) ──────────
    # Number of shards the risk_enforcer is split across. DEFAULT 1 =
    # single-worker, co-located on `leader:feed`, prices read in-process —
    # BYTE-FOR-BYTE today's behaviour. Set > 1 (and <= worker count /
    # WEB_CONCURRENCY) ONLY when `risk_enforcer_tick_overrun` is sustained
    # > 1-2 s: users are then partitioned by user_id hash across N shard
    # workers (`leader:risk:shard:0..N-1`), each reading prices from the
    # leader's Redis `mdlive` snapshot. Flip back to 1 to instantly revert.
    # Change ONLY when the market is closed (a shard-count change re-hashes
    # users for one tick; the atomic-claim dedup covers that transition).
    RISK_SHARDS: int = 1

    # Risk-loop tick interval (seconds). The risk_enforcer sweep (bracket
    # SL/TP + margin stop-out) runs every RISK_TICK_SEC on each shard.
    # 0.5 s proved too aggressive for the current book + single-box infra:
    # the busiest shard (a whale user holding ~70 of ~120 open positions —
    # sharding can't split ONE user) couldn't finish its sweep inside 0.5 s,
    # so risk_enforcer_tick_overrun fired continuously. 1.0 s gives every
    # shard 2× the budget AND halves the per-second Mongo/Redis/CPU load
    # (fewer contention spikes), while still reacting to a stop-out / SL / TP
    # within ~1 s — 5× faster than the legacy 5 s loop and imperceptible to
    # users. Lower back toward 0.5 only once the busiest shard's total_ms
    # sits comfortably under the chosen interval.
    RISK_TICK_SEC: float = 1.0

    # ── Redis ────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    # Bumped from 50 → 300 after the market_tick_loop started raising
    # `ConnectionError: Too many connections` once the Zerodha WS pool
    # crossed ~1500 subscribed tokens. Every 250 ms tick publishes one
    # message per token over pub/sub, plus the order validator + cache
    # helpers all pull from the same pool. Empirical headroom needed
    # ≈ token_count / 20 + steady ~50 for HTTP path; 300 leaves slack
    # for spikes during option-chain expansion.
    REDIS_MAX_CONNECTIONS: int = 300

    # ── WebSocket limits ─────────────────────────────────────────────
    # Hard cap on simultaneous WebSocket connections per client IP,
    # enforced via Redis (see app/core/ws_limiter.py). Generous default
    # so users on shared NAT exits / corporate proxies aren't penalised;
    # set to 0 to disable the limiter entirely.
    WS_MAX_CONNECTIONS_PER_IP: int = 100
    # Per-connection cap on instrument-token subscriptions on the
    # `/ws/marketdata` socket. Each subscribed token costs one slot in
    # the in-process ``MarketTickHub`` fanout map and one entry in the
    # upstream Zerodha / Infoway ticker — a power-user holding 200+
    # symbols in one watchlist would otherwise multiply tick-publish
    # work across the whole worker pool. 70 fits a typical user's full
    # watchlist + the option-chain expansion they have open at once,
    # with headroom; bigger requests get rejected with an explicit
    # `subscription_limit` error frame so the frontend can prompt the
    # user to unsubscribe something first.
    WS_MAX_SUBSCRIPTIONS_PER_CONN: int = 70

    # ── JWT ──────────────────────────────────────────────────────────
    # Refresh-token TTL widened from 7 → 30 days so the mobile app keeps
    # users logged in for a month (matches Zerodha / Groww / Upstox UX).
    # The token rotates on every refresh so a fresh login resets the
    # 30-day window — a daily-active user effectively never sees a login
    # screen unless they sign out explicitly or revoke from another device.
    JWT_SECRET: SecretStr = Field(default=SecretStr("change-me"))
    JWT_ALGORITHM: str = "HS256"
    # Access token bumped from 15 → 1440 min (24 h) so the silent-refresh
    # cycle fires at most once a day instead of every 15 min. User-flagged
    # symptom on the installed PWA: "30 din set hai fir bhi logout ho
    # raha hai". Cause was a transient refresh failure (PWA resume before
    # network reattaches, backend deploy mid-suspend, etc.) which the
    # frontend interceptor used to convert into a hard /login redirect.
    # Longer access lifetime + revised frontend retry semantics together
    # close that hole. Backend revocation is still instantaneous because
    # /auth/refresh + the JTI allow-list rotate on every refresh, so a
    # logout from another device kills the next refresh attempt — the
    # access token only lives until its own TTL after that, which 24 h
    # is still well within the security budget for a personal trading
    # app.
    JWT_ACCESS_TTL_MIN: int = 1440
    JWT_REFRESH_TTL_DAYS: int = 30

    # ── Admin extra security ─────────────────────────────────────────
    ADMIN_API_KEY: SecretStr = Field(default=SecretStr("change-me-admin"))
    ADMIN_IP_WHITELIST: str = ""

    # ── CORS ─────────────────────────────────────────────────────────
    CORS_USER_ORIGIN: str = "http://localhost:3000"
    CORS_ADMIN_ORIGIN: str = "http://localhost:3001"

    # ── Public backend URL (used by OAuth callback URLs etc.) ────────
    # Override in production to your actual API hostname, e.g.
    # https://api.setupfx.com — Kite redirects the user's browser here.
    BACKEND_PUBLIC_URL: str = "http://localhost:8000"

    # ── Rate limit ───────────────────────────────────────────────────
    RATE_LIMIT_AUTH_PER_MIN: int = 5
    RATE_LIMIT_DEFAULT_PER_MIN: int = 100
    RATE_LIMIT_TRADING_PER_MIN: int = 300

    # ── External APIs ────────────────────────────────────────────────
    ANGEL_ONE_API_KEY: str = ""
    ANGEL_ONE_CLIENT_CODE: str = ""
    ANGEL_ONE_CLIENT_PIN: str = ""
    ANGEL_ONE_TOTP_SECRET: str = ""
    ZERODHA_API_KEY: str = ""
    ZERODHA_API_SECRET: str = ""
    # AES-256-GCM key for encrypting the Zerodha auto-login credentials at rest.
    # 32 raw bytes, base64-encoded. Generate with:
    #   python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"
    # If unset, the auto-login service refuses to save credentials so a
    # misconfigured deploy can't accidentally store plaintext.
    ZERODHA_CREDS_KEY: SecretStr = Field(default=SecretStr(""))
    PRICE_FEED_PROVIDER: Literal["mock", "angel_one", "zerodha"] = "mock"

    # Infoway — global forex / crypto / metals / energy / stocks / indices feed.
    INFOWAY_API_KEY: SecretStr = Field(default=SecretStr(""))
    INFOWAY_AUTO_CONNECT: bool = True
    INFOWAY_DEFAULT_CRYPTO: str = "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,BNBUSDT"
    # NOTE: keep this list pure forex pairs (6-char major/minor crosses). Don't
    # add USDINR here — Indian-rupee derivatives belong on the NSE/BSE CDS
    # segment, not the international Infoway forex bucket the user-side
    # "Forex" chip surfaces.
    INFOWAY_DEFAULT_FOREX: str = "EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD,USDCHF,NZDUSD"
    # Spot precious metals + common energy contracts (Infoway uses the same
    # ticker style — XAUUSD = gold/USD, XAGUSD = silver/USD, USOIL = WTI).
    INFOWAY_DEFAULT_METALS: str = "XAUUSD,XAGUSD,XPTUSD,XPDUSD"
    INFOWAY_DEFAULT_ENERGY: str = "USOIL,UKOIL,NATGAS"
    # International equities subscribe through Infoway's dedicated `stock`
    # WebSocket business channel (US / HK / A-share coverage). Indices
    # share the `common` channel with forex/metals/energy. Both are
    # treated as explicit allowlists by `_classify_infoway_code` so an
    # AAPL-shaped string can't be mis-routed as a forex pair.
    # Defaults cover the most-traded US tickers + global indices; admin
    # can override via env without code changes.
    INFOWAY_DEFAULT_STOCKS: str = "AAPL,MSFT,GOOGL,AMZN,TSLA,NVDA,META,NFLX"
    INFOWAY_DEFAULT_INDICES: str = "SPX500,NAS100,US30,UK100,DE40,JPN225,HK50"

    # Binance — free, keyless public crypto price feed. Replaces the Infoway
    # `crypto` channel: ticks flow into the SAME shared tick cache and the SAME
    # `infoway:tick:*` Redis channel that market-data / user-WS / the games BTC
    # resolver already read, so no consumer changes. Forex / metals / energy
    # stay on Infoway (idle unless INFOWAY_API_KEY is set — key removed = off).
    BINANCE_ENABLED: bool = True
    BINANCE_WS_BASE: str = "wss://stream.binance.com:9443"
    BINANCE_SYMBOLS: str = "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,BNBUSDT"

    # ── Binance crypto OPTIONS (European, USDT-settled) — eapi ──────────
    # Phase 1 = view-only chain + live prices. Poll-based (one REST call for
    # all marks + one for all tickers), no key. OFF by default; the operator
    # flips BINANCE_OPTIONS_ENABLED=true to turn the feed on. Underlyings are
    # the option "baseAsset" roots (BTC only for the first release). The mirror
    # keeps only the nearest N expiries and strikes within ±X% of spot so the
    # instrument universe stays small.
    # Allow opening trades at the LAST-KNOWN price even when the market is
    # closed / the live feed has no fresh tick (a challenge/demo platform must
    # be tradeable 24×7 at the last price — operator: "turant last price pe
    # trade"). When True the order validator skips the market-hours + live-tick
    # gates for opening orders; the matching engine still fills at the client's
    # expected_price and its zero-price guard blocks a genuinely dead 0-price.
    ALLOW_TRADE_AT_LAST_PRICE: bool = True

    BINANCE_OPTIONS_ENABLED: bool = False
    BINANCE_OPTIONS_EAPI_BASE: str = "https://eapi.binance.com"
    BINANCE_OPTIONS_UNDERLYINGS: str = "BTC"
    BINANCE_OPTIONS_POLL_SEC: float = 2.0
    BINANCE_OPTIONS_MAX_EXPIRIES: int = 3
    BINANCE_OPTIONS_STRIKE_PCT: float = 15.0  # keep strikes within ±15% of spot

    # MetaAPI (metaapi.cloud) — forex / metals / energy feed via a connected
    # MT4/MT5 broker account. Ticks land in the SAME shared cache + `infoway:
    # tick:*` Redis channel every consumer reads (mirrors binance_service). The
    # service auto-maps platform symbols (XAUUSD, EURUSD, USOIL…) to the broker's
    # actual symbol names (many brokers suffix, e.g. `XAUUSD.#`), so it only
    # feeds whatever the broker actually offers. CRYPTO is NEVER written here —
    # it stays on Binance. Off unless METAAPI_AUTO_CONNECT + token + account set.
    METAAPI_TOKEN: SecretStr = Field(default=SecretStr(""))
    METAAPI_ACCOUNT_ID: str = ""
    METAAPI_AUTO_CONNECT: bool = False
    METAAPI_REGION: str = ""  # optional; SDK auto-discovers when blank
    METAAPI_DEFAULT_FOREX: str = "EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD,USDCHF,NZDUSD"
    METAAPI_DEFAULT_METALS: str = "XAUUSD,XAGUSD,XPTUSD,XPDUSD"
    METAAPI_DEFAULT_ENERGY: str = "USOIL,UKOIL,NATGAS"
    METAAPI_POLL_SEC: float = 0.7

    # ── Yahoo Finance (gap-filler feed) ──────────────────────────────
    # Serves ONLY the symbols no other feed covers — forex pairs, indices,
    # US stocks, energy/platinum futures. Keyless. Never overwrites a fresh
    # tick from Binance/MetaAPI (see yahoo_service._should_write), so it can
    # be left on permanently. NOTE: index + futures quotes are 10–15 minutes
    # delayed — safe to display, NOT safe to trade. See the module docstring.
    YAHOO_ENABLED: bool = True
    YAHOO_POLL_SEC: float = 10.0

    # ── Email / SMS ──────────────────────────────────────────────────
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: SecretStr = Field(default=SecretStr(""))
    SMTP_FROM: str = "no-reply@setupfx.com"
    SMTP_TLS: bool = True
    SMS_PROVIDER: Literal["mock", "twilio", "msg91"] = "mock"
    SMS_API_KEY: SecretStr = Field(default=SecretStr(""))
    SMS_SENDER_ID: str = "STPFX"

    # ── S3 ───────────────────────────────────────────────────────────
    S3_BUCKET: str = ""
    S3_REGION: str = "ap-south-1"
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: SecretStr = Field(default=SecretStr(""))
    S3_ENDPOINT_URL: str = ""

    # ── Celery ───────────────────────────────────────────────────────
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── Observability ────────────────────────────────────────────────
    SENTRY_DSN: str = ""
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    # ── Web Push (VAPID) ─────────────────────────────────────────────
    # RFC 8292 application-server identity. The browser hands these
    # back at subscribe time and the push service uses them to verify
    # that the message originated from us. Generate ONCE per
    # deployment and keep the private key secret; rotating it
    # invalidates every existing subscription so users have to
    # re-subscribe (i.e. re-grant notification permission).
    # Quick-gen:
    #     python -m scripts.generate_vapid_keys
    # leave blank in dev — push send is a no-op until both are set.
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: SecretStr = Field(default=SecretStr(""))
    VAPID_SUBJECT: str = "mailto:admin@stockex.com"

    # ── Seed ─────────────────────────────────────────────────────────
    SEED_SUPER_ADMIN_EMAIL: str = "admin@setupfx.com"
    SEED_SUPER_ADMIN_PASSWORD: SecretStr = Field(default=SecretStr("Admin@123"))
    SEED_SUPER_ADMIN_MOBILE: str = "9999999999"
    RUN_SEED_ON_STARTUP: bool = True

    # ── Trading ──────────────────────────────────────────────────────
    DEFAULT_TIMEZONE: str = "Asia/Kolkata"
    MARKET_OPEN_TIME: str = "09:15"
    MARKET_CLOSE_TIME: str = "15:30"
    MUHURAT_OPEN_TIME: str = "18:15"
    MUHURAT_CLOSE_TIME: str = "19:15"

    # ── White-label branding ─────────────────────────────────────────
    # Master kill-switch for the white-label branding subsystem. When
    # False (default), the new schema fields on User exist but no code
    # path reads/writes them, the `/api/v1/branding/*` endpoints (added
    # in Phase 2) return 503, and the frontend BrandingProvider falls
    # back to default platform branding. Flip to True only after Phase
    # 1 is observed clean for ≥ 24h. Keeps prod 0-second reversible.
    BRANDING_ENABLED: bool = False

    # ── Multi-wallet (per-segment trading wallets — wallet.md) ───────────
    # When True, all trading margin / P&L / risk route to the instrument's
    # SEGMENT wallet (NSE_BSE / MCX / CRYPTO / FOREX) instead of the single
    # Main wallet. A one-shot boot migration seeds segment wallets from Main.
    # Flip to False to instantly revert to the legacy single-wallet path.
    MULTI_WALLET_ENABLED: bool = True
    # When a trading (segment) wallet's loss takes it below zero, first pull the
    # shortfall out of the user's MAIN cash wallet (where deposits land and
    # trading wallets are funded from) if it has balance — so a trading wallet
    # going into minus is auto-covered from available cash before it becomes a
    # settlement/negative balance. Only what MAIN can afford is pulled (MAIN
    # never goes negative); any remainder follows the per-wallet auto-settlement
    # rule (floor+book, or go negative). Default ON — flip OFF to keep trading
    # wallets fully isolated from MAIN.
    SEGMENT_SHORTFALL_COVER_FROM_MAIN: bool = True
    # Stability window (seconds) for the 3 Nifty games' clearing close. At
    # settlement the resolver reads the fresh Zerodha quote but only LOCKS it
    # once the value has held STEADY for this long — so it never settles on a
    # pre-clearing tick or a flaky-feed value. NSE's official clearing close
    # (last-30-min VWAP) lands a little after 15:30 and the quote keeps moving
    # until it settles on it; we wait for it to stop moving, HOWEVER long the
    # feed takes to connect properly (feed down → keeps waiting). Correctness
    # over speed. Raise for a stricter wait, lower for faster results.
    GAMES_NIFTY_CLEARING_DELAY_SEC: int = 90

    # ── Admin float / fund-cap (SA→admin allocation caps user funding) ───
    # When True, an admin/broker crediting a downline USER (deposit-approve,
    # manual credit) DEBITS the owning-admin's own float (Wallet.available_
    # balance) and is BLOCKED when the float is insufficient; a user
    # withdrawal REPLENISHES that float. SA is always unlimited (never
    # capped/debited). Default OFF — flip ON only after each admin has been
    # given a float (else existing admins with 0 float can't fund anyone).
    ADMIN_FLOAT_ENABLED: bool = False
    # Public IPv4 the platform answers on — admins point their custom
    # domain's A records here for DNS verification (Phase 4). Empty
    # default keeps the verify endpoint a no-op when unset.
    PLATFORM_PUBLIC_IP: str = ""

    # ─────────────────────────────────────────────────────────────────
    @field_validator("MONGODB_URL")
    @classmethod
    def _validate_mongo_url(cls, v: str) -> str:
        if not v.startswith(("mongodb://", "mongodb+srv://")):
            raise ValueError("MONGODB_URL must start with mongodb:// or mongodb+srv://")
        return v

    @field_validator("REDIS_URL")
    @classmethod
    def _validate_redis_url(cls, v: str) -> str:
        if not v.startswith(("redis://", "rediss://", "unix://")):
            raise ValueError("REDIS_URL must start with redis://, rediss://, or unix://")
        return v

    # ── Production fail-closed secrets guard ─────────────────────────
    @model_validator(mode="after")
    def _enforce_production_secrets(self) -> "Settings":
        """Refuse to BOOT in production if any security-critical secret is
        still a placeholder/dev value, the seed super-admin password is the
        well-known default, debug is on, or MongoDB has no credentials.

        Development / staging are intentionally exempt so local work keeps
        using the convenient defaults. This is the safety net that stops a
        misconfigured deploy from shipping with:
          • a forgeable JWT_SECRET (anyone could mint a valid admin token),
          • a publicly-known ADMIN_API_KEY,
          • the Admin@123 seed password,
          • an unauthenticated MongoDB (anyone on the network could read
            wallets / overwrite the super-admin password hash),
          • debug tracebacks leaking internals to clients.
        """
        if self.APP_ENV != "production":
            return self

        problems: list[str] = []

        jwt_secret = self.JWT_SECRET.get_secret_value()
        if len(jwt_secret) < 32 or "change" in jwt_secret.lower():
            problems.append(
                "JWT_SECRET is weak/placeholder — use a random secret of ≥32 chars"
            )

        api_key = self.ADMIN_API_KEY.get_secret_value()
        if len(api_key) < 24 or "change" in api_key.lower():
            problems.append(
                "ADMIN_API_KEY is weak/placeholder — use a random key of ≥24 chars"
            )

        seed_pw = self.SEED_SUPER_ADMIN_PASSWORD.get_secret_value()
        if seed_pw in {"Admin@123", "", "change-me"}:
            problems.append(
                "SEED_SUPER_ADMIN_PASSWORD is the default — set a strong unique password"
            )

        if self.APP_DEBUG:
            problems.append("APP_DEBUG must be false in production")

        # An authenticated Mongo URI always carries credentials as
        # `user:pass@host`. No '@' ⇒ no auth ⇒ the DB is open to anyone who
        # can reach the port. (Atlas / any authed deploy passes this.)
        if "@" not in self.MONGODB_URL:
            problems.append(
                "MONGODB_URL has no credentials — enable MongoDB auth (SCRAM) in production"
            )

        if problems:
            raise ValueError(
                "Refusing to start: insecure production config detected:\n  - "
                + "\n  - ".join(problems)
                + "\nFix these in the production .env (see backend/SECURITY.md)."
            )
        return self

    @property
    def admin_ip_whitelist_set(self) -> set[str]:
        return {ip.strip() for ip in self.ADMIN_IP_WHITELIST.split(",") if ip.strip()}

    @property
    def cors_allowed_origins(self) -> list[str]:
        """Flatten both CORS_USER_ORIGIN and CORS_ADMIN_ORIGIN, splitting
        comma-separated values so each origin lands as its own list entry
        (Starlette's CORSMiddleware compares origins as exact strings — a
        single list entry like `"https://a,https://b"` matches nothing)."""
        raw = f"{self.CORS_USER_ORIGIN},{self.CORS_ADMIN_ORIGIN}"
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def zerodha_redirect_url(self) -> str:
        """Canonical Kite-Connect callback URL. Always lives on the backend
        because the request_token exchange happens server-side."""
        base = (self.BACKEND_PUBLIC_URL or "http://localhost:8000").rstrip("/")
        return f"{base}/api/v1/admin/zerodha/callback"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
