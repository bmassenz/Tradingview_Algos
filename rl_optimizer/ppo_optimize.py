"""PPO parameter search with a cross-asset, walk-forward composite reward.

Formulation: a one-step episodic environment (contextual bandit). Each action is a
full parameter vector; the reward is the composite score of that parameter set
backtested independently on SPY, QQQ, SMH and IWM over the in-sample window,
penalised for out-of-sample degradation and for cross-asset dispersion. PPO learns
a Gaussian policy over the parameter space; its clipped updates act as a trust
region, and the entropy of the policy decays as it concentrates on robust regions.

The HOLDOUT window (2023+) is never evaluated here.
"""
import argparse
import json
import os
import time

import gymnasium as gym
import numpy as np
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import SubprocVecEnv

from data_loader import SYMBOLS, load
from engine import Asset, backtest
from metrics import WINDOWS, composite_reward, window_metrics
from space import DIM, ORIGINAL_RAW, decode, encode

OUT_DIR = os.path.join(os.path.dirname(__file__), "results")


def evaluate(assets, p, windows=("IS", "OOS")):
    per = {}
    for s, a in assets.items():
        eq, _, tr = backtest(a, p)
        per[s] = {w: window_metrics(a, eq, tr, *WINDOWS[w]) for w in windows}
    return per


class ParamEnv(gym.Env):
    def __init__(self, log_path):
        super().__init__()
        self.assets = {s: Asset(s, load(s)) for s in SYMBOLS}
        self.action_space = gym.spaces.Box(-1.0, 1.0, (DIM,), np.float32)
        self.observation_space = gym.spaces.Box(-1.0, 1.0, (1,), np.float32)
        self.log = open(log_path, "a")

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        return np.zeros(1, np.float32), {}

    def step(self, action):
        p = decode(action)
        raw = p.pop("_raw")
        try:
            per = evaluate(self.assets, p)
            reward, brk = composite_reward(per)
        except Exception as e:  # invalid combination: strongly negative, keep learning
            reward, brk, per = -20.0, {"error": str(e)}, {}
        rec = dict(reward=reward, raw=raw, breakdown=brk,
                   summary={s: {w: {k: round(v, 4) for k, v in m.items()} for w, m in d.items()} for s, d in per.items()})
        self.log.write(json.dumps(rec) + "\n")
        self.log.flush()
        return np.zeros(1, np.float32), float(max(reward, -20.0)), True, False, {}


def make_env(path):
    def _f():
        return ParamEnv(path)
    return _f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=24000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--envs", type=int, default=4)
    ap.add_argument("--tag", default="run")
    ap.add_argument("--init", default="", help="selection JSON whose chosen_raw seeds the policy mean")
    args = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    torch.set_num_threads(1)
    log_paths = [os.path.join(OUT_DIR, f"{args.tag}_s{args.seed}_w{i}.jsonl") for i in range(args.envs)]
    for lp in log_paths:
        open(lp, "w").close()
    venv = SubprocVecEnv([make_env(lp) for lp in log_paths])
    model = PPO(
        "MlpPolicy", venv, seed=args.seed, verbose=0,
        n_steps=128, batch_size=128, n_epochs=10, learning_rate=1e-3,
        gamma=0.0, gae_lambda=1.0, clip_range=0.2, ent_coef=0.0, normalize_advantage=True,
        policy_kwargs=dict(net_arch=dict(pi=[32], vf=[32]), log_std_init=-0.7),
    )
    # Start the policy mean at the original script's parameters
    with torch.no_grad():
        start_raw = json.load(open(args.init))["chosen_raw"] if args.init else ORIGINAL_RAW
        model.policy.action_net.bias.copy_(torch.tensor(encode(start_raw), dtype=torch.float32))
        model.policy.action_net.weight.mul_(0.0)
    t0 = time.time()
    model.learn(total_timesteps=args.steps)
    mean_action, _ = model.predict(np.zeros((1,), np.float32), deterministic=True)
    std = np.exp(model.policy.log_std.detach().numpy())
    json.dump(dict(mean_action=mean_action.tolist(), std=std.tolist(), seconds=time.time() - t0),
              open(os.path.join(OUT_DIR, f"{args.tag}_s{args.seed}_policy.json"), "w"))
    model.save(os.path.join(OUT_DIR, f"{args.tag}_s{args.seed}_ppo"))
    venv.close()
    print("done in %.0fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
