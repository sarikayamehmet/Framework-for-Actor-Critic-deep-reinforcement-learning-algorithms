import numpy as np
from collections import deque
from sortedcontainers import SortedDict

class Buffer(object):
	# __slots__ = ('types', 'size', 'batches')
	
	def __init__(self, size):
		self.size = size
		self.clean()
		
	def clean(self):
		self.types = {}
		self.batches = []
		
	def get_batches(self, type_id=None):
		if type_id is None:
			result = []
			for value in self.types.values():
				result += self.batches[value]
			return result
		return self.batches[self.get_type(type_id)]

	def has_atleast(self, frames, type=None):
		return self.count(type) >= frames
		
	def has(self, frames, type=None):
		return self.count(type) == frames
		
	def count(self, type=None):
		if type is None:
			if len(self.batches) == 0:
				return 0
			return sum(len(batch) for batch in self.batches)
		return len(self.batches[type])
		
	def id_is_full(self, type_id):
		return self.has(self.size, self.get_type(type_id))
		
	def is_full(self, type=None):
		if type is None:
			return self.has(self.size*len(self.types))
		return self.has(self.size, type)
		
	def is_empty(self, type=None):
		return not self.has_atleast(1, type)
		
	def get_type(self, type_id):
		self.add_type(type_id)
		return self.types[type_id]
		
	def add_type(self, type_id):
		if type_id in self.types:
			return
		self.types[type_id] = len(self.types)
		self.batches.append(deque())

	def put(self, batch, type_id=0): # put batch into buffer
		type = self.get_type(type_id)
		if self.is_full(type):
			self.batches[type].popleft()
		self.batches[type].append(batch)

	def sample(self):
		# assert self.has_atleast(frames=1)
		type = np.random.choice( [value for value in self.types.values() if not self.is_empty(value)] )
		id = np.random.randint(0, len(self.batches[type]))
		return self.batches[type][id]

class PrioritizedBuffer(Buffer):
	
	def __init__(self, size):
		self._eps = 1e-6
		self._alpha = 0.6
		super().__init__(size)
	
	def clean(self):
		super().clean()
		self.prefixsum = []
		
	def get_batches(self, type_id=None):
		if type_id is None:
			result = []
			for type in self.types.values():
				result += self.batches[type].values()
			return result
		return self.batches[self.get_type(type_id)].values()
		
	def add_type(self, type_id):
		if type_id in self.types:
			return
		self.types[type_id] = len(self.types)
		self.batches.append(SortedDict())
		self.prefixsum.append([])
		
	def get_batch_priority(self, priority):
		return self._eps + (np.abs(priority)**self._alpha)
		
	def put(self, batch, priority, type_id=0): # O(log)
		type = self.get_type(type_id)
		if self.is_full(type):
			self.batches[type].popitem(index=0) # argument with lowest priority is always 0 because buffer is sorted by priority
		batch_priority = self.get_batch_priority(priority)
		self.batches[type].update({batch_priority: batch}) # O(log)
		self.prefixsum[type] = None # compute prefixsum only if needed, when sampling
		
	def sample(self): # O(n) after a new put, O(log) otherwise
		type_id = np.random.choice( [key for key,value in self.types.items() if not self.is_empty(value)] )
		type = self.get_type(type_id)
		if self.prefixsum[type] is None: # compute prefixsum
			self.prefixsum[type] = np.cumsum(self.batches[type].keys()) # O(n)
		mass = np.random.random() * self.prefixsum[type][-1]
		idx = np.searchsorted(self.prefixsum[type], mass) # O(log) # Find arg of leftmost item greater than or equal to x
		keys = self.batches[type].keys()
		return self.batches[type][keys[idx]], idx, type_id

	def update_priority(self, idx, priority, type_id=0): # O(log)
		type = self.get_type(type_id)
		_, batch = self.batches[type].popitem(index=idx) # argument with lowest priority is always 0 because buffer is sorted by priority
		self.put(batch, priority, type_id)