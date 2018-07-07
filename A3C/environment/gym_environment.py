# -*- coding: utf-8 -*-
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

# get command line args
import options
flags = options.get()

import gym
from environment import environment
import collections
import numpy as np
        
class GymEnvironment(environment.Environment):
	
	def __init__(self, thread_index, environment_name):
		environment.Environment.__init__(self)
		self.thread_index = thread_index
		# setup environment
		self.game = gym.make(environment_name)
		self.real_actions = self.game.action_space
		# evaluator stuff
		self.episodes = collections.deque()
		self.use_ram = "-ram" in environment_name

	def reset(self):
		self.stop()
		self.last_state = self.game.reset()
		# self.last_state = np.copy(self.last_state)
		self.last_state = self.normalize(self.last_state)
		self.last_action = 0
		self.last_reward = 0
		self.cumulative_reward = 0
		self.step = 0
		
	def normalize(self, state):
		while len(state.shape) < 3:
			state = np.expand_dims(state, axis=-1)
		return state
			
	def get_action_size(self):
		return self.real_actions.n
		
	def get_state_shape(self):
		shape = self.game.observation_space.shape
		while len(shape) < 3:
			shape = shape + (1,)
		return shape
		
	def stop(self):
		self.game.close()
		
	def get_statistics(self):
		result = {}
		result["avg_reward"] = 0
		result["avg_steps"] = 0
		count = len(self.episodes)
		if count>0:
			for e in self.episodes:
				result["avg_steps"] += e["step"]
				result["avg_reward"] += e["reward"]
			result["avg_steps"] /= count
			result["avg_reward"] /= count
		return result
		
	def get_screen(self):
		return self.last_state
		
	def get_frame_info(self, value_estimator_network):
		if self.use_ram: # ram
			screen_info = {
				"reward": self.last_reward,
				"action": self.last_action,
				"agent": value_estimator_network.agent_id,
			}
			augmented_screen = [str(["{0}={1}".format(key,value) for key, value in screen_info.items()]) + '\n'] + [np.array_str(self.get_screen().flatten())]
			return { "screen": '\n'.join(augmented_screen) }
		else: # rgb image
			return { "rgb": self.get_screen() }
		
	def get_last_action_reward(self):
		action_reward = np.zeros(self.get_action_size()+1, dtype=np.uint8)
		action_reward[self.last_action]=1
		action_reward[-1] = self.last_reward
		return action_reward
		
	def process(self, action):
		action = action%self.get_action_size()
		# self.game.render(mode='rgb_array')
		new_state, reward, done, info = self.game.step(action)
		# new_state = np.copy(new_state)
		new_state = self.normalize(new_state)
		
		self.last_state = new_state
		self.last_action = action
		self.last_reward = reward
		self.cumulative_reward += reward
		self.step += 1
		if done: # add to statistics
			self.episodes.append( {"reward":self.cumulative_reward, "step":self.step} )
			if len(self.episodes) > flags.match_count_for_evaluation:
				self.episodes.popleft()
		return new_state, reward, done