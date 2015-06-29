
"""
Created on Mon Jun 29 18:39:11 2015

@author: CJSB
"""

from PyGMO.problem import base as base_problem
from PyKEP import epoch,DAY2SEC,planet_ss,MU_SUN,lambert_problem,propagate_lagrangian,fb_prop, AU
from math import pi, cos, sin, acos
from scipy.linalg import norm

class mga_1dsm_tof(base_problem):
	"""
	This class represents a global optimization problem (box-bounded, continuous) relative to an interplanetary trajectory modelled
	as a Multiple Gravity Assist trajectory that allows one only Deep Space Manouvre between each leg.

	SEE : Izzo: "Global Optimization and Space Pruning for Spacecraft Trajectory Design, Spacecraft Trajectory Optimization, Conway, B. (Eds.), Cambridge University Press, pp.178-199, 2010)

	The decision vector is [t0,u,v,Vinf,eta1] + [beta, rp/rV, eta2]... + [T1, T2...] ..... in the units: [mjd2000,nd,nd,km/s,nd,years] + [rad,nd,nd,nd] + ....
	where Vinf = Vinf_mag*(cos(theta)*cos(phi)i+cos(theta)*sin(phi)j+sin(phi)k) and theta = 2*pi*u and phi = acos(2*v-1)-pi/2

	Each leg time-of-flight is defined as T[i];

	NOTE: The resulting problem is box-bounded (unconstrained). The resulting trajectory is time-bounded.

	"""
	def __init__(self, 
			seq = [planet_ss('earth'),planet_ss('venus'),planet_ss('earth')], 
			t0 = [epoch(0),epoch(1000)],
			tof = [[100, 200],[200, 300]],             
			vinf = [3,5],
			add_vinf_dep=False, 
			add_vinf_arr=True,  
			multi_objective = False):
		"""
		Constructs an mga_1dsm_tof problem

		USAGE: traj.mga_1dsm(seq = [planet_ss('earth'),planet_ss('venus'),planet_ss('earth')], t0 = [epoch(0),epoch(1000)], tof = [[100, 200],[200, 300]], vinf = [0.5, 2.5], multi_objective = False, add_vinf_dep = False, add_vinf_arr=True)

		* seq: list of PyKEP planets defining the encounter sequence (including the starting launch)
		* t0: list of two epochs defining the launch window
		* tof: containing a list of intervals for the time of flight of each leg (days)
		* vinf: list of two floats defining the minimum and maximum allowed initial hyperbolic velocity (at launch), in km/sec
		* multi_objective: when True constructs a multiobjective problem (dv, T)
		* add_vinf_dep: when True the computed Dv includes the initial hyperbolic velocity (at launch)
		* add_vinf_arr: when True the computed Dv includes the final hyperbolic velocity (at the last planet)
		"""
		
		#Sanity checks ...... all planets need to have the same mu_central_body
		if ( [r.mu_central_body for r in seq].count(seq[0].mu_central_body)!=len(seq) ):
			raise ValueError('All planets in the sequence need to have exactly the same mu_central_body')
		self.__add_vinf_dep = add_vinf_dep
		self.__add_vinf_arr = add_vinf_arr
		self.__n_legs = len(seq) - 1
		dim = 5 + (self.__n_legs-1) * 3 + (self.__n_legs)* 1 
		obj_dim = multi_objective + 1
		
		#First we call the constructor for the base PyGMO problem 
		#As our problem is n dimensional, box-bounded (may be multi-objective), we write
		#(dim, integer dim, number of obj, number of con, number of inequality con, tolerance on con violation)
		
		super(mga_1dsm_tof,self).__init__(dim,0,obj_dim,0,0,0)

		#We then define all planets in the sequence  and the common central body gravity as data members
		self.seq = seq
		self.common_mu = seq[0].mu_central_body
		
		#And we compute the bounds
		lb = [t0[0].mjd2000,0.0,0.0,vinf[0]*1000,1e-5] + [-2*pi, 1.1,1e-5 ] * (self.__n_legs-1) + [1]*self.__n_legs
		ub = [t0[1].mjd2000,1.0,1.0,vinf[1]*1000,1.0-1e-5] + [2*pi, 30.0,1.0-1e-5] * (self.__n_legs-1) + [700]*self.__n_legs
		
		for i in range(0, self.__n_legs):
			lb[4+3*(self.__n_legs-1) + i+1] = tof[i][0]
			ub[4+3*(self.__n_legs-1) + i+1] = tof[i][1]
		
		#Accounting that each planet has a different safe radius......        
		for i,pl in enumerate(seq[1:-1]):
      
			lb[6+3*i] = pl.safe_radius / pl.radius
			
		#And we set them
		self.set_bounds(lb,ub)

	#Objective function
	def _objfun_impl(self,x):
		#1 -  we 'decode' the chromosome recording the various times of flight (days) in the list T

		T = list([0]*(self.__n_legs))
		for i in range(0,self.__n_legs):
			T[i] = x[4+3*(self.__n_legs - 1) + i+1]
  
		#2 - We compute the epochs and ephemerides of the planetary encounters
		t_P = list([None] * (self.__n_legs+1))
		r_P = list([None] * (self.__n_legs+1))
		v_P = list([None] * (self.__n_legs+1))
		DV = list([0.0] * (self.__n_legs+1))
		
		for i,planet in enumerate(self.seq):
			t_P[i] = epoch(x[0] + sum(T[0:i]))
			r_P[i],v_P[i] = self.seq[i].eph(t_P[i])
			

		#3 - We start with the first leg
		theta = 2*pi*x[1]
		phi = acos(2*x[2]-1)-pi/2

		Vinfx = x[3]*cos(phi)*cos(theta)
		Vinfy = x[3]*cos(phi)*sin(theta)
		Vinfz = x[3]*sin(phi)

		v0 = [a+b for a,b in zip(v_P[0],[Vinfx,Vinfy,Vinfz])]
		r,v = propagate_lagrangian(r_P[0],v0,x[4]*T[0]*DAY2SEC,self.common_mu)

		#Lambert arc to reach seq[1]
		dt = (1-x[4])*T[0]*DAY2SEC
		l = lambert_problem(r,r_P[1],dt,self.common_mu, False, False)
		v_end_l = l.get_v2()[0]
		v_beg_l = l.get_v1()[0]

		#First DSM occuring at time nu1*T1
		DV[0] = norm([a-b for a,b in zip(v_beg_l,v)])

		#4 - And we proceed with each successive leg
		for i in range(1,self.__n_legs):
			#Fly-by 
			v_out = fb_prop(v_end_l,v_P[i],x[6+(i-1)*3]*self.seq[i].radius,x[5+(i-1)*3],self.seq[i].mu_self)
			#s/c propagation before the DSM
			r,v = propagate_lagrangian(r_P[i],v_out,x[7+(i-1)*3]*T[i]*DAY2SEC,self.common_mu)
			#Lambert arc to reach Earth during (1-nu2)*T2 (second segment)
			dt = (1-x[7+(i-1)*3])*T[i]*DAY2SEC
			l = lambert_problem(r,r_P[i+1],dt,self.common_mu, False, False)
			v_end_l = l.get_v2()[0]
			v_beg_l = l.get_v1()[0]
			#DSM occuring at time nu2*T2
			DV[i] = norm([a-b for a,b in zip(v_beg_l,v)])


		#Last Delta-v
		if self.__add_vinf_arr:
			DV[-1] = norm([a-b for a,b in zip(v_end_l,v_P[-1])])
		
		if self.__add_vinf_dep:
			DV[0] += x[3]

		if self.f_dimension == 1:
			return (sum(DV),)
		else:
			return (sum(DV), sum(T))

	def pretty(self,x):
		"""
		Prints human readable information on the trajectory represented by the decision vector x
		
		Example::
		
		  prob.pretty(x)
		"""
		#1 -  we 'decode' the chromosome recording the various times of flight (days) in the list T
		T = list([0]*(self.__n_legs))
		for i in range(0, self.__n_legs):
			T[i] = x[4+3*(self.__n_legs - 1) + i+1]
		
		#2 - We compute the epochs and ephemerides of the planetary encounters
		t_P = list([None] * (self.__n_legs+1))
		r_P = list([None] * (self.__n_legs+1))
		v_P = list([None] * (self.__n_legs+1))
		DV = list([None] * (self.__n_legs+1))
		
		for i,planet in enumerate(self.seq):
			t_P[i] = epoch(x[0] + sum(T[0:i]))
			r_P[i],v_P[i] = self.seq[i].eph(t_P[i])

		#3 - We start with the first leg
		print "First Leg: " + self.seq[0].name + " to " + self.seq[1].name 
		
		theta = 2*pi*x[1]
		phi = acos(2*x[2]-1)-pi/2

		Vinfx = x[3]*cos(phi)*cos(theta)
		Vinfy =	x[3]*cos(phi)*sin(theta)
		Vinfz = x[3]*sin(phi)
		
		print "Departure: " + str(t_P[0]) + " (" + str(t_P[0].mjd2000) + " mjd2000) " 
		print "Duration: " + str(T[0]) + "days"
		print "VINF: " + str(x[3] / 1000) + " km/sec"

		v0 = [a+b for a,b in zip(v_P[0],[Vinfx,Vinfy,Vinfz])]
		r,v = propagate_lagrangian(r_P[0],v0,x[4]*T[0]*DAY2SEC,self.common_mu)
		
		print "DSM after " + str(x[4]*T[0]) + " days"

		#Lambert arc to reach seq[1]
		dt = (1-x[4])*T[0]*DAY2SEC
		l = lambert_problem(r,r_P[1],dt,self.common_mu, False, False)
		v_end_l = l.get_v2()[0]
		v_beg_l = l.get_v1()[0]

		#First DSM occuring at time nu1*T1
		DV[0] = norm([a-b for a,b in zip(v_beg_l,v)])
		print "DSM magnitude: " + str(DV[0]) + "m/s"

		#4 - And we proceed with each successive leg
		for i in range(1,self.__n_legs):
			print "\nleg no. " + str(i+1) + ": " + self.seq[i].name + " to " + self.seq[i+1].name 
			print "Duration: " + str(T[i]) + "days"
			#Fly-by 
			v_out = fb_prop(v_end_l,v_P[i],x[6+(i-1)*3]*self.seq[i].radius,x[5+(i-1)*3],self.seq[i].mu_self)
			print "Fly-by epoch: " + str(t_P[i]) + " (" + str(t_P[i].mjd2000) + " mjd2000) " 
			print "Fly-by radius: " + str(x[6+(i-1)*3]) + " planetary radii"
			#s/c propagation before the DSM
			r,v = propagate_lagrangian(r_P[i],v_out,x[7+(i-1)*3]*T[i]*DAY2SEC,self.common_mu)
			print "DSM after " + str(x[7+(i-1)*3]*T[i]) + " days"
			#Lambert arc to reach Earth during (1-nu2)*T2 (second segment)
			dt = (1-x[7+(i-1)*4])*T[i]*DAY2SEC
			l = lambert_problem(r,r_P[i+1],dt,self.common_mu, False, False)
			v_end_l = l.get_v2()[0]
			v_beg_l = l.get_v1()[0]
			#DSM occuring at time nu2*T2
			DV[i] = norm([a-b for a,b in zip(v_beg_l,v)])
			print "DSM magnitude: " + str(DV[i]) + "m/s"

		#Last Delta-v
		print "\nArrival at " + self.seq[-1].name
		DV[-1] = norm([a-b for a,b in zip(v_end_l,v_P[-1])])
		print "Arrival epoch: " + str(t_P[-1]) + " (" + str(t_P[-1].mjd2000) + " mjd2000) " 
		print "Arrival Vinf: " + str(DV[-1]) + "m/s"
		print "Total mission time: " + str(sum(T)/365.25) + " years"


	#Plot of the trajectory
	def plot(self,x):
		"""
		Plots the trajectory represented by the decision vector x
		
		Example::
		
		  prob.plot(x)
		"""
		import matplotlib as mpl
		from mpl_toolkits.mplot3d import Axes3D
		import matplotlib.pyplot as plt
		from PyKEP.orbit_plots import plot_planet, plot_lambert, plot_kepler

		mpl.rcParams['legend.fontsize'] = 10
		fig = plt.figure()
		axis = fig.gca(projection='3d')
		axis.scatter(0,0,0, color='y')
		
		#1 -  we 'decode' the chromosome recording the various times of flight (days) in the list T
		
		T = list([0]*(self.__n_legs))
		for i in range(0, self.__n_legs):
			T[i] = x[4+3*(self.__n_legs - 1) + i+1]
		
		#2 - We compute the epochs and ephemerides of the planetary encounters
		t_P = list([None] * (self.__n_legs+1))
		r_P = list([None] * (self.__n_legs+1))
		v_P = list([None] * (self.__n_legs+1))
		DV = list([None] * (self.__n_legs+1))
		
		for i,planet in enumerate(self.seq):
			t_P[i] = epoch(x[0] + sum(T[0:i]))
			r_P[i],v_P[i] = planet.eph(t_P[i])
			plot_planet(planet, t0=t_P[i], color=(0.8,0.6,0.8), legend=True, units = AU, ax=axis)

		#3 - We start with the first leg
		theta = 2*pi*x[1]
		phi = acos(2*x[2]-1)-pi/2

		Vinfx = x[3]*cos(phi)*cos(theta)
		Vinfy =	x[3]*cos(phi)*sin(theta)
		Vinfz = x[3]*sin(phi)

		v0 = [a+b for a,b in zip(v_P[0],[Vinfx,Vinfy,Vinfz])]
		r,v = propagate_lagrangian(r_P[0],v0,x[4]*T[0]*DAY2SEC,self.common_mu)
		plot_kepler(r_P[0],v0,x[4]*T[0]*DAY2SEC,self.common_mu,N = 100, color='b', legend=False, units = AU, ax=axis)

		#Lambert arc to reach seq[1]
		dt = (1-x[4])*T[0]*DAY2SEC
		l = lambert_problem(r,r_P[1],dt,self.common_mu, False, False)
		plot_lambert(l, sol = 0, color='r', legend=False, units = AU, ax=axis)
		v_end_l = l.get_v2()[0]
		v_beg_l = l.get_v1()[0]

		#First DSM occurring at time nu1*T1
		DV[0] = norm([a-b for a,b in zip(v_beg_l,v)])

		#4 - And we proceed with each successive leg
		for i in range(1,self.__n_legs):
			#Fly-by 
			v_out = fb_prop(v_end_l,v_P[i],x[6+(i-1)*3]*self.seq[i].radius,x[5+(i-1)*3],self.seq[i].mu_self)
			#s/c propagation before the DSM
			r,v = propagate_lagrangian(r_P[i],v_out,x[7+(i-1)*3]*T[i]*DAY2SEC,self.common_mu)
			plot_kepler(r_P[i],v_out,x[7+(i-1)*3]*T[i]*DAY2SEC,self.common_mu,N = 100, color='b', legend=False, units = AU, ax=axis)
			#Lambert arc to reach Earth during (1-nu2)*T2 (second segment)
			dt = (1-x[7+(i-1)*4])*T[i]*DAY2SEC

			l = lambert_problem(r,r_P[i+1],dt,self.common_mu, False, False)
			plot_lambert(l, sol = 0, color='r', legend=False, units = AU, N=1000, ax=axis)

			v_end_l = l.get_v2()[0]
			v_beg_l = l.get_v1()[0]
			#DSM occurring at time nu2*T2
			DV[i] = norm([a-b for a,b in zip(v_beg_l,v)])
		plt.show()
		return axis
			
	def set_launch_window(self, start, end):
		"""
		Sets the launch window allowed in terms of starting and ending epochs
		
		Example::
		
		  start = epoch(0)
		  end = epoch(1000)
		  prob.set_launch_window(start, end)
		"""
		lb = list(self.lb)
		ub = list(self.ub)
		lb[0] = start.mjd2000
		ub[0] = end.mjd2000
		self.set_bounds(lb,ub)
		
	def set_vinf(self, vinf_lb, vinf_ub):
		"""
		Sets the allowed launch vinf (in km/s)
		
		Example::
		  
		  M = 5
		  prob.set_vinf(M)
		"""
		lb = list(self.lb)
		ub = list(self.ub)
		lb[3] = vinf_lb*1000
		ub[3] = vinf_ub * 1000
		self.set_bounds(lb,ub)
		
	def human_readable_extra(self):
             return ("\n\t Sequence: " + [pl.name for pl in self.seq].__repr__() +
		     "\n\t Add launcher vinf to the objective?: " + self.__add_vinf_dep.__repr__() +
		     "\n\t Add final vinf to the objective?: " + self.__add_vinf_arr.__repr__())
