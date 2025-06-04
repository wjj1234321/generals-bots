import functools
from copy import deepcopy
from typing import Any, TypeAlias

import numpy as np
import pettingzoo  # type: ignore
from gymnasium import spaces

from generals.core.game import Action, Game, Info, Observation
from generals.core.grid import Grid, GridFactory
from generals.core.replay import Replay
from generals.core.rewards import RewardFn, WinLoseRewardFn
from generals.gui import GUI
from generals.gui.properties import GuiMode

AgentID: TypeAlias = str


class PettingZooGenerals(pettingzoo.ParallelEnv):
    metadata: dict[str, Any] = {
        "render_modes": ["human"],
        "render_fps": 6,
    }

    def __init__(
        self,
        agents: list[str],
        grid_factory: GridFactory | None = None,
        truncation: int | None = None,
        reward_fn: RewardFn | None = None,
        render_mode: str | None = None,
        speed_multiplier: float = 1.0,
    ):
        """
        Args:
            agents: A dictionary of the agent-ids & agents.
            grid_factory: Can be used to specify the game-board i.e. grid generator.
            truncation: The maximum number of turns a game can last before it's truncated.
            reward_fn: An instance of the RewardFn abstract base class.
            render_mode: "human" will provide a real-time graphic of the game. None will
                show no graphics and run the game as fast as possible.
            speed_multiplier: Relatively increase or decrease the speed of the real-time
                game graphic. This has no effect if render_mode is None.
            pad_observations: If True, the observations will be padded to the same shape,
                defined by maximum grid dimensions of grid_factory.
        """
        self.render_mode = render_mode
        self.speed_multiplier = speed_multiplier

        self.grid_factory = grid_factory if grid_factory is not None else GridFactory()
        self.reward_fn = reward_fn if reward_fn is not None else WinLoseRewardFn()

        # Agents
        self.agents = agents
        self.colors = [(2, 107, 108), (0, 10, 255)]
        self.agent_data = {id: {"color": color} for id, color in zip(agents, self.colors)}
        self.possible_agents = self.agents

        # Observations for each agent at the prior time-step.
        self.prior_observations: dict[str, Observation] | None = None

        assert len(self.possible_agents) == len(
            set(self.possible_agents)
        ), "Agent ids must be unique - you can pass custom ids to agent constructors."
        self.truncation = truncation

    @functools.cache
    def observation_space(self, agent: AgentID) -> spaces.Space:
        """
        If grid_factory has padding on, grid (and therefore observations) will be padded to the same shape,
        which corresponds to the maximum grid dimensions of grid_factory.
        Otherwise, the observatoin shape might change depending on the currently generated grid.

        Note: The grid is padded with mountains from right and bottom. We recommend using the padded
        grids for training purposes, as it will make the observations consistent across episodes.
        """
        assert agent in self.possible_agents, f"Agent {agent} not in possible agents"
        if self.grid_factory.padding:
            dims = self.grid_factory.max_grid_dims
        else:
            dims = self.game.grid_dims
        max_army_value = 100_000
        max_timestep = 100_000
        max_land_value = np.prod(dims)
        grid_multi_binary = spaces.MultiBinary(dims)
        grid_discrete = np.ones(dims, dtype=int) * 100_000
        return spaces.Dict(
            {
                "armies": spaces.MultiDiscrete(grid_discrete),
                "generals": grid_multi_binary,
                "cities": grid_multi_binary,
                "mountains": grid_multi_binary,
                "neutral_cells": grid_multi_binary,
                "owned_cells": grid_multi_binary,
                "opponent_cells": grid_multi_binary,
                "fog_cells": grid_multi_binary,
                "structures_in_fog": grid_multi_binary,
                "owned_land_count": spaces.Discrete(max_land_value),
                "owned_army_count": spaces.Discrete(max_army_value),
                "opponent_land_count": spaces.Discrete(max_land_value),
                "opponent_army_count": spaces.Discrete(max_army_value),
                "timestep": spaces.Discrete(max_timestep),
                "priority": spaces.Discrete(2),
            }
        )

    @functools.cache
    def action_space(self, agent: AgentID) -> spaces.Space:
        assert agent in self.possible_agents, f"Agent {agent} not in possible agents"
        if self.grid_factory.padding:
            dims = self.grid_factory.max_grid_dims
        else:
            dims = self.game.grid_dims
        return spaces.MultiDiscrete([2, dims[0], dims[1], 4, 2])

    def render(self):
        if self.render_mode == "human":
            _ = self.gui.tick(fps=self.speed_multiplier * self.metadata["render_fps"])

    def reset(
        self, seed: int | None = None, options: dict | None = None
    ) -> tuple[dict[AgentID, Observation], dict[AgentID, dict]]:
        if options is None:
            options = {}
        self.agents = deepcopy(self.possible_agents)
        if "grid" in options:
            grid = Grid(options["grid"])
        else:
            # The pettingzoo.Parallel_Env's reset() notably differs
            # from gymnasium.Env's reset() in that it does not create
            # a random generator which should be re-used.
            self.grid_factory.set_rng(rng=np.random.default_rng(seed))
            grid = self.grid_factory.generate()

        self.game = Game(grid, self.agents)

        if self.render_mode == "human":
            self.gui = GUI(self.game, self.agent_data, GuiMode.TRAIN, self.speed_multiplier)

        if "replay_file" in options:
            self.replay = Replay(
                name=options["replay_file"],
                grid=grid,
                agent_data=self.agent_data,
            )
            self.replay.add_state(deepcopy(self.game.channels))
        elif hasattr(self, "replay"):
            del self.replay

        observations = {agent: self.game.agent_observation(agent) for agent in self.agents}
        infos: dict[str, Any] = {agent: {} for agent in self.agents}
        return observations, infos

    def step(
        self, actions: dict[AgentID, Action]
    ) -> tuple[
        dict[AgentID, Observation],
        dict[AgentID, float],
        dict[AgentID, bool],
        dict[AgentID, bool],
        dict[AgentID, Info],
    ]:
        observations, infos = self.game.step(actions)
        observations = {agent: observation for agent, observation in observations.items()}
        # You probably want to set your truncation based on self.game.time
        truncated = False if self.truncation is None else self.game.time >= self.truncation
        terminated = self.game.is_done()

        if self.prior_observations is None:
            # Cannot compute rewards without prior-observations. This should only happen
            # on the first time-step.
            rewards = {agent: 0.0 for agent in self.agents}
        else:
            rewards = {
                agent: self.reward_fn(
                    prior_obs=self.prior_observations[agent],
                    # Technically actions are the prior-actions, since they are what will give
                    # rise to the current-observations.
                    prior_action=actions[agent],
                    obs=observations[agent],
                )
                for agent in self.agents
            }

        if hasattr(self, "replay"):
            self.replay.add_state(deepcopy(self.game.channels))

        # if any agent dies, all agents are terminated
        if terminated or truncated:
            self.agents = []
            if hasattr(self, "replay"):
                self.replay.store()

        self.prior_observations = observations

        return observations, rewards, terminated, truncated, infos
