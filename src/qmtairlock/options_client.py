"""Client option pricing, implied volatility and Greeks from native input data."""

from .option_analytics import black_scholes_price, implied_volatility


class OptionsClient:
    def __init__(self, data):
        self.data = data

    def bsm_price(self, opt_type, target_price, strike_price, risk_free, sigma, days, dividend=0):
        return black_scholes_price(
            opt_type, target_price, strike_price, float(days) / 365.0, risk_free, sigma, dividend
        )

    def bsm_iv(self, opt_type, target_price, strike_price, option_price, risk_free, days, dividend=0):
        return implied_volatility(
            opt_type, target_price, strike_price, option_price, float(days) / 365.0, risk_free, dividend
        )

    def get_option_analytics(
        self,
        opt_code,
        option_price=None,
        underlying_price=None,
        as_of=None,
        risk_free_rate=None,
        dividend_yield=None,
        price_period="1m",
        include_native_iv=False,
    ):
        """Return client-side IV and Greeks for one option contract."""
        from .option_analytics_client import get_option_analytics

        return get_option_analytics(
            self.data,
            opt_code,
            option_price=option_price,
            underlying_price=underlying_price,
            as_of=as_of,
            risk_free_rate=risk_free_rate,
            dividend_yield=dividend_yield,
            price_period=price_period,
            include_native_iv=include_native_iv,
        )

    def get_option_chain_analytics(
        self,
        undl_code,
        dedate,
        opttype="",
        isavailavle=False,
        underlying_price=None,
        as_of=None,
        risk_free_rate=None,
        dividend_yield=None,
        price_period="1m",
    ):
        """Return batched client-side IV and Greeks for one option expiry."""
        from .option_analytics_client import get_option_chain_analytics

        return get_option_chain_analytics(
            self.data,
            undl_code,
            dedate,
            opttype=opttype,
            isavailavle=isavailavle,
            underlying_price=underlying_price,
            as_of=as_of,
            risk_free_rate=risk_free_rate,
            dividend_yield=dividend_yield,
            price_period=price_period,
        )
