from generals import GridFactory, PettingZooGenerals
from generals.agents import RandomAgent, ExpanderAgent
import time

agent = ExpanderAgent()
agent.id = 'smart1'

npc = ExpanderAgent()
npc.id = 'smart2'

# Initialize grid factory
grid_factory = GridFactory(
     # alternatively "generalsio", which will override other parameters
    grid_dims=(15, 15),
    mountain_density=0.2,  # Expected percentage of mountains
    city_density=0.05,  # Expected percentage of cities
    seed = 121,  # Seed to generate the same map every time
)

agents = {
    agent.id: agent,
    npc.id: npc,
}



env = PettingZooGenerals(agents=agents, grid_factory=grid_factory, render_mode="human")


# We can draw custom maps - see symbol explanations in README
grid = """
..#...##..
..A.#..4..
.3...1....
...###....
####...9.B
...###....
.2...5....
....#..6..
..#...##..
"""

# Options are used only for the next game
options = {
    "replay_file": "my_replay",  # If specified, save replay as my_replay.pkl
    # "grid": grid,  # Use the custom map
}

observations, info = env.reset(options=options)
terminated = truncated = {}
step_count = 0
while not any(terminated.values()):
    actions = {}
    for agent in env.agents: #每轮所有玩家同时决定一次操作
        action = agents[agent].act(observations[agent]) #告诉玩家视野
        # 检查 agent 行为是否合法
        if action is None:
            raise ValueError(f"Agent {agent} 在第 {step_count} 步返回了 None 动作，可能实现有误。")
        actions[agent] = action #记录所有玩家的移动
    print(f"Step {step_count}, actions: {actions}")
    observations, rewards, terminated, truncated, info = env.step(actions) #执行移动，并输出信息
    print(f"rewards: {rewards}, terminated: {terminated}, truncated: {truncated}")
    env.render() #更新画面
    step_count += 1



print("游戏结束，窗口将在5秒后关闭...")
time.sleep(5)