
"""
Created on Tue Jun 02 17:19:44 2015

@author: CJSB
"""
def Rosetta():
    
    from PyGMO import archipelago, problem
    from PyGMO.algorithm import jde
    from PyGMO.topology import ring

    from PyKEP import epoch, AU, DEG2RAD, MU_SUN, planet
    from PyKEP import planet_ss
    from PyKEP.trajopt import mga_1dsm_tof
    
    # from matplotlib import pyplot as plt
   
    # The comet is the 67P/Churyumov-Geramisenko
    churyumov = planet (epoch(7976),(3.4559747*AU, 0.6497023, 3.87139*DEG2RAD, 36.33226*DEG2RAD, 22.13412*DEG2RAD, 359.99129*DEG2RAD),MU_SUN,667.384,2000,2100,'67P Churyumov-Geramisenko')
    
    seq = [planet_ss('earth'), planet_ss('earth'), planet_ss('mars'), planet_ss('earth'), planet_ss('earth'), churyumov]
	
    prob = mga_1dsm_tof(seq=seq, tof=[[300,500],[150,800],[150,800],[300,800],[700,1850]], add_vinf_dep=False, add_vinf_arr=True)
    
    prob.set_vinf(3,5) # In km/s
    prob.set_launch_window(epoch(1400), epoch(1900)) # 2010-2025
    
    print prob

    algo = jde(200) # Self-adaptive differential evolution algorithm
    topo = ring() # Ring topology (links go in both directions)

    print(
        "Running a Self-Adaptive Differential Evolution Algorithm .... on 8 parallel islands")
    
    #archi.evolve(10) # Each of the 8 islands will call algo 10 times and try to migrate between calls
    #archi.join() # waits for it to finish
    #[isl.population.champion.f for isl in archi]
    
    l = list()
    for i in range(10):
        archi = archipelago (algo,prob, 8, 20,topology=topo)
        for j in range(30):
            archi.evolve(3)
            print min([isl.population.champion.f[0] for isl in archi])
        tmp = [isl for isl in archi]; tmp.sort(key=lambda x:x.population.champion.f[0]);
        l.append(tmp[0].population.champion)
    print "Results: \n"
    print [ch.f[0] for ch in l]
    
    l.sort(key = lambda x: x.f[0])
    x_so = l[0].x
    prob.plot(x_so)
    print prob.pretty(x_so)

