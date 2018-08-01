import math
import numpy as np
import operator
from scipy import optimize

# get command line args
import options
flags = options.get()

from collections import deque
import matplotlib
matplotlib.use('Agg') # non-interactive back-end
from matplotlib import pyplot as plt

from environment.environment import Environment
	
class CarControllerEnvironment(Environment):

	def get_state_shape(self):
		return (1,5,2)

	def get_action_shape(self):
		return (1,) # steering angle, continuous control
	
	def __init__(self, thread_index):
		Environment.__init__(self)
		self.thread_index = thread_index
		self.max_distance_to_path = .5
		self.noise = .2
		self.speed = .1 # meters per step
		self.max_angle_degrees = 45
		self.points_number = 100
		self.max_steps = self.points_number
		self.max_angle_radians = convert_degree_to_radians(self.max_angle_degrees)
		# evaluator stuff
		self.episodes = deque()
		
	def build_random_path(self):
		# setup environment
		self.U1, self.V1 = generate_random_polynomial()
		self.U2, self.V2 = generate_random_polynomial()
		# we generate all points for both polynomials, then we shall draw only a portion of them
		self.points = np.linspace(start=0, stop=1, num=self.points_number)
		theta = angle(1, self.U1, self.V1)
		xv,yv = poly(self.points,self.U1), poly(self.points,self.V1)
		xv2,yv2 = rotate_and_shift(poly(self.points,self.U2),poly(self.points,self.V2),xv[-1],yv[-1],theta)
		x = np.concatenate((xv,xv2),axis=0) # length 200
		y = np.concatenate((yv,yv2),axis=0) # length 200
		return x, y
		
	def is_terminal_position(self, position):
		return position > self.points_number
		
	def reset(self):
		self.car_position = (0, 0) #car position and orientation are always expressed with respect to the initial position and orientation of the road fragment
		self.path = self.build_random_path()
		self.relative_path, self.next_position = get_relative_path_and_next_position(point=self.car_position, path=self.path) #now we shift to car vision
		if self.is_terminal_position(self.next_position):
			reset()
		else:
			self.cumulative_reward = 0
			self.last_action = 0
			self.last_state = self.get_state(car_position=self.car_position)
			self.last_reward = 0
			self.steps = 0
			self.progress_point = 0
		
	def get_last_action_reward(self):
		return [self.last_action, self.last_reward]
		
	def compute_new_car_position(self, car_position, compensation_angle):
		car_x, car_y = car_position
		car_angle = norm(angle(self.points[self.next_position], self.U1, self.V1)) # use the tangent to path as default direction -> more stable results
		car_angle = norm(car_angle + compensation_angle) # adjust the default direction using the compensation_angle
		# update position
		car_x += self.speed*np.cos(car_angle)
		car_y += self.speed*np.sin(car_angle)
		# car_x += self.speed*np.cos(compensation_angle)
		# car_y += self.speed*np.sin(compensation_angle)
		return (car_x, car_y)
		
	def get_noisy_position(self, position):
		x, y = position
		# add noise to position
		x += (2*np.random.random()-1)*self.noise
		y += (2*np.random.random()-1)*self.noise
		return (x, y)

	def process(self, policy):
		self.steps += 1
		policy_choice=0
		action = np.clip(policy[policy_choice],0,1)
		# get agent steering angle and car position
		compensation_angle = (2*action-1)*self.max_angle_radians
		# update car position
		self.car_position = self.compute_new_car_position(car_position=self.car_position, compensation_angle=compensation_angle)
		# update next position
		self.relative_path, new_next_position = get_relative_path_and_next_position(point=self.car_position, path=self.path) # shift path to car vision
		if new_next_position > self.next_position:
			self.next_position = new_next_position
		# get state and reward
		state = self.get_state(car_position=self.get_noisy_position(self.car_position))
		reward = self.get_reward(car_position=self.car_position, next_position=self.next_position)
		terminal = self.is_terminal_position(self.next_position) or self.steps >= self.max_steps
		# populate statistics
		if terminal:
			self.episodes.append( {"reward":self.cumulative_reward, "step": self.steps, "completed": 1 if self.is_terminal_position(self.next_position) else 0} )
			if len(self.episodes) > flags.match_count_for_evaluation:
				self.episodes.popleft()
		# update last action/state/reward
		self.last_state = state
		self.last_reward = reward
		self.last_action = action
		# update cumulative reward
		self.cumulative_reward += reward
		return policy_choice, state, reward, terminal
		
	def get_reward(self, car_position, next_position):
		car_x, car_y = car_position
		def get_distance(point):
			x, y = poly(point,self.U1), poly(point,self.V1)
			return math.sqrt((car_x-x)**2 + (car_y-y)**2)
		a = self.progress_point
		b = self.points[next_position] if next_position < self.points_number else 1
		result = optimize.minimize_scalar(get_distance, bounds=(a,b)) # find the closest spline point
		if result.x > self.progress_point: # is moving toward next position
			self.progress_point = result.x
			distance = get_distance(self.points[next_position]) if next_position < self.points_number else get_distance(1)
			return 1 - np.clip(distance/self.max_distance_to_path,0,1) # always in [0,1] # smaller distances to path give higher rewards
		return -1 # is NOT moving toward next position
		
	def get_state(self, car_position):
		car_x, car_y = car_position
		shape = self.get_state_shape()
		state = np.zeros(shape)
		state[0][0] = [car_x, car_y]
		for i in range(1,shape[1]):
			state[0][i] = [self.U1[i-1],self.V1[i-1]]
		return state
		
	def get_screen(self):
		xc, yc = self.relative_path
		position = self.next_position
		xct = xc[position:min(position+self.points_number,2*self.points_number)] if position < len(xc) else []
		yct = yc[position:min(position+self.points_number,2*self.points_number)] if position < len(xc) else []
		return (xct,yct)
		
	def get_frame_info(self, network, observation, policy, value, action, reward):
		state_info = "reward={}, action={}, agent={}, value={}\n".format(reward, action, network.agent_id, value)
		policy_info = "policy={}\n".format(policy)
		frame_info = { "log": state_info + policy_info }
		if flags.save_episode_screen:
			# First set up the figure, the axis, and the plot element we want to animate
			fig, ax = plt.subplots(nrows=1, ncols=1, sharey=False, sharex=False, figsize=(10,10))
			line, = ax.plot(observation[0], observation[1], lw=2)
			ax.plot(0,0,"ro")
			fig.canvas.draw()
			# Now we can save it to a numpy array.
			data = np.fromstring(fig.canvas.tostring_rgb(), dtype=np.uint8, sep='')
			data = data.reshape(fig.canvas.get_width_height()[::-1] + (3,))
			plt.close(fig) # release memory
			frame_info["screen"] = { "value": data, "type": 'RGB' }
		return frame_info
		
	def get_statistics(self):
		result = {}
		result["avg_reward"] = 0
		result["avg_step"] = 0
		result["avg_completed"] = 0
		count = len(self.episodes)
		if count>0:
			for e in self.episodes:
				result["avg_reward"] += e["reward"]
				result["avg_step"] += e["step"]
				result["avg_completed"] += e["completed"]
			result["avg_reward"] /= count
			result["avg_step"] /= count
			result["avg_completed"] /= count
		return result
		
def rot(x,y,theta):
	#rotation and translation
	xnew = x*np.cos(theta)- y*np.sin (theta)
	ynew = x*np.sin(theta) + y*np.cos(theta) 
	return(xnew,ynew)

def shift_and_rotate(xv,yv,dx,dy,theta):
	#xv and yv are lists
	xy = zip(xv,yv)
	xynew = [rot(c[0]+dx,c[1]+dy,theta) for c in xy]
	xyunzip = list(zip(*xynew))
	return(xyunzip[0],xyunzip[1])

def rotate_and_shift(xv,yv,dx,dy,theta):
	#xv and yv are lists
	xy = zip(xv,yv)
	xynew = [tuple(map(operator.add,rot(c[0],c[1],theta),(dx,dy))) for c in xy]
	xyunzip = list(zip(*xynew))
	return(xyunzip[0],xyunzip[1])

def generate_random_polynomial():
	#both x and y are defined by two polynomials in a third variable p, plus
	#an initial angle (that, when connecting splines, will be the same as
	#the final angle of the previous polynomial)
	#Both polynomials are third order.
	#The polynomial for x is aU, bU, cU, dU
	#The polynomial for y is aV, bV, cV, dV
	#aU and bU are always 0 (start at origin) and bV is always 0 (derivative at
	#origin is 0). bU must be positive
	# constraints initial coordinates must be the same as
	# ending coordinates of the previous polynomial
	aU = 0
	aV = 0
	# initial derivative must the same as the ending
	# derivative of the previous polynomial
	bU = (10-6)*np.random.random()+6  #around 8
	bV = 0
	#we randonmly generate values for cU and dU in the range ]-1,1[
	cU = 2*np.random.random()-1
	dU = 2*np.random.random()-1
	finalV = 10*np.random.random()-5
	#final derivative between -pi/6 and pi/6
	finald = np.tan((np.pi/3)*np.random.random() - np.pi/6)
	#now we fix parameters to meet the constraints:
	#bV + cV + dV = finalV 
	#angle(1) = finald; see the definition of angle below
	Ud = bU + 2*cU + 3*dU
	#Vd = bU + 2*cU + 3*dU = finald*Ud
	dV = finald*Ud - 2*finalV + bV
	cV = finalV - dV - bV
	return ((aU,bU,cU,dU), (aV,bV,cV,dV))

def poly(p, points):
	(a,b,c,d) = points
	return a + b*p + c*p**2 + d*p**3

def derivative(p, points):
	(a,b,c,d) = points
	return b + 2*c*p + 3*d*p**2

def angle(p, U, V):
	Ud = derivative(p,U)
	Vd = derivative(p,V)
	return (np.arctan(Vd/Ud)) if abs(Ud) > abs(Vd/1000) else (np.pi/2)
	
def norm(angle):
    if angle >= np.pi:
        angle -= 2*np.pi
    elif angle < -np.pi:
        angle += 2*np.pi
    return angle

def convert_degree_to_radians(degree):
	return (degree/180)*np.pi
	
def get_relative_path_and_next_position(point, path):
	point_x, point_y = point
	path_xs, path_ys = path
	relative_path = shift_and_rotate(path_xs, path_ys, -point_x, -point_y, 0)
	xc, yc = relative_path
	next_position = 0
	while next_position < len(xc) and xc[next_position] < 0:
		next_position +=1
	return relative_path, next_position