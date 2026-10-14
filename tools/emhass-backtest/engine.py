"""Build EMHASS optimisers from the repo's emhass/config.json, as the add-on does."""
import asyncio
import copy
import logging
import pathlib

import emhass
import pandas as pd
from emhass.optimization import Optimization
from emhass.utils import build_config, build_params, get_yaml_parse

PKG = pathlib.Path(emhass.__file__).parent
HERE = pathlib.Path(__file__).parent
REPO_CONFIG = HERE.parent.parent / "emhass" / "config.json"
TZ = "Pacific/Auckland"

logger = logging.getLogger("backtest")
logger.setLevel(logging.ERROR)
for name in ("emhass", "cvxpy"):
    logging.getLogger(name).setLevel(logging.ERROR)

(HERE / "data" / "emhass").mkdir(parents=True, exist_ok=True)
EMHASS_CONF = {
    "data_path": HERE / "data" / "emhass",
    "root_path": PKG,
    "defaults_path": PKG / "data" / "config_defaults.json",
    "associations_path": PKG / "data" / "associations.csv",
    "config_path": REPO_CONFIG,
}


def _base_confs():
    async def go():
        config = await build_config(EMHASS_CONF, logger, EMHASS_CONF["defaults_path"], REPO_CONFIG)
        # Location and HA connection are unused: prices, PV and load are all passed in.
        secrets = {"time_zone": TZ, "Latitude": 0, "Longitude": 0, "Altitude": 0,
                   "hass_url": "http://localhost:8123", "long_lived_token": "unused"}
        params = await build_params(EMHASS_CONF, secrets, config, logger)
        return get_yaml_parse(params, logger)
    return asyncio.run(go())


_BASE = _base_confs()
_cache = {}


def _optimiser(overrides, n):
    key = (tuple(sorted(overrides.items())), n)
    if key not in _cache:
        rh, oc, pc = (copy.deepcopy(c) for c in _BASE)
        for k, v in overrides.items():  # plant keys (efficiencies, ...) vs optim keys
            (pc if k in pc else oc)[k] = v
        _cache[key] = Optimization(rh, oc, pc, "unit_load_cost", "unit_prod_price", "profit",
                                   EMHASS_CONF, logger, num_timesteps=n)
    return _cache[key]


def plan(overrides, index, load_cost, prod_price, pv, load, soc_init, soc_final=0.12):
    """One naive-MPC solve; overrides are optim_conf or plant_conf keys."""
    df = pd.DataFrame({"unit_load_cost": load_cost, "unit_prod_price": prod_price}, index=index)
    opt = _optimiser(overrides, len(index))
    return opt.perform_naive_mpc_optim(df, pd.Series(pv, index=index), pd.Series(load, index=index),
                                       len(index), soc_init, soc_final)
