#!/usr/bin/env python

# for python 2 / 3 compatibility
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

try :
    range = xrange
except NameError :
    pass

try :
    import ConfigParser as configparser 
except ImportError :
    import configparser 

import numpy as np
import h5py 
import argparse
import os, sys
import re
import copy

# import python modules using the relative directory 
# locations this way the repository can be anywhere 
root = os.path.split(os.path.abspath(__file__))[0]
root = os.path.split(root)[0]
sys.path = [os.path.join(root, 'utils')] + sys.path

import io_utils
import duck_3D
import forward_sim
import phasing_3d
# testing
import maps_gpu as maps
#import maps
import fidelity


def config_iters_to_alg_num(string):
    # split a string like '100ERA 200DM 50ERA' with the numbers
    steps = re.split('(\d+)', string)   # ['', '100', 'ERA ', '200', 'DM ', '50', 'ERA']
    
    # get rid of empty strings
    steps = [s for s in steps if len(s)>0] # ['100', 'ERA ', '200', 'DM ', '50', 'ERA']
    
    # pair alg and iters
    # [['ERA', 100], ['DM', 200], ['ERA', 50]]
    alg_iters = [ [steps[i+1].strip(), int(steps[i])] for i in range(0, len(steps), 2)]
    return alg_iters

def phase(mapper, iters_str = '100DM 100ERA', beta=1):
    """
    phase a crappy crystal diffraction volume
    
    Parameters
    ----------
    mapper : object
        A class object that can be used by 3D-phasing, which
        requires the following methods:
            I     = mapper.Imap(modes)   # mapping the modes to the intensity
            modes = mapper.Pmod(modes)   # applying the data projection to the modes
            modes = mapper.Psup(modes)   # applying the support projection to the modes
            O     = mapper.object(modes) # the main object of interest
            dict  = mapper.finish(modes) # add any additional output to the info dict
    
    Keyword Arguments
    -----------------
    iters_str : str, optional, default ('100DM 100ERA')
        supported iteration strings, in general it is '[number][alg][space]'
        [N]DM [N]ERA 1cheshire
    """
    alg_iters = config_iters_to_alg_num(iters_str)
    
    Cheshire_error_map = None
    eMod = []
    eCon = []
    O    = mapper.object(mapper.modes)
    for alg, iters in alg_iters :
        
        print(alg, iters)
        
        if alg == 'ERA':
           O, mapper, info = phasing_3d.ERA(iters, mapper = mapper)
         
        if alg == 'DM':
           O, mapper, info = phasing_3d.DM(iters, mapper = mapper, beta=beta)
        
        if alg == 'cheshire':
           O, info = mapper.scans_cheshire(O, scan_points=None)
           Cheshire_error_map = info['error_map'].copy()
         
        print('\n\nupdating eMod:', len(info['eMod']), len(eMod))
        eMod += list(copy.copy(info['eMod']))
        eCon += list(copy.copy(info['eCon']))
        print(len(info['eMod']), len(eMod))
        

    if Cheshire_error_map is not None :
        info['Cheshire_error_map'] = Cheshire_error_map
    
    info['unit_cell'] = np.sum(mapper.modes.get(), axis=0)
    # temp
    #modes = info['modes'] #mapper.Pmod(mapper.modes)
    #O     = mapper.object(modes)
    return O, mapper, eMod, eCon, info

def parse_cmdline_args(default_config='phase.ini'):
    parser = argparse.ArgumentParser(description="phase a crappy crystal from it's diffraction intensity. The results are output into a .h5 file.")
    parser.add_argument('-f', '--filename', type=str, \
                        help="file name of the output *.h5 file to edit / create")
    parser.add_argument('-c', '--config', type=str, \
                        help="file name of the configuration file")
    
    args = parser.parse_args()
    
    # if config is non then read the default from the *.h5 dir
    if args.config is None :
        args.config = os.path.join(os.path.split(args.filename)[0], default_config)
        if not os.path.exists(args.config):
            args.config = '../process/' + default_config
    
    # check that args.config exists
    if not os.path.exists(args.config):
        raise NameError('config file does not exist: ' + args.config)
    
    # process config file
    config = configparser.ConfigParser()
    config.read(args.config)
    
    params = io_utils.parse_parameters(config)[default_config[:-4]]
    
    # check that the output file was specified
    ################################################
    if args.filename is None and params['output_file'] is not None :
        fnam = params['output_file']
        args.filename = fnam
    
    if args.filename is None :
        raise ValueError('output_file in the ini file is not valid, or the filename was not specified on the command line')
    
    return args, params


if __name__ == '__main__':
    args, params = parse_cmdline_args()
    
    # make the input
    ################
    if params['input_file'] is None :
        f = h5py.File(args.filename)
    else :
        f = h5py.File(params['input_file'])

    # data
    I = f[params['data']][()]
    
    # solid unit
    if params['solid_unit'] is None :
        solid_unit = None
    else :
        print('loading solid_unit from file...')
        solid_unit = f[params['solid_unit']][()]
    
    # detector mask
    if params['mask'] is None :
        mask = None
    else :
        mask = f[params['mask']][()]
    
    # voxel support
    if params['voxels'] is None :
        voxels = None
    elif type(params['voxels']) != int and params['voxels'][0] == '/'  :
        voxels = f[params['voxels']][()]
    else :
        voxels = params['voxels']
    
    # voxel_sup_blur support
    if params['voxel_sup_blur'] is None :
        voxel_sup_blur = None
    elif type(params['voxel_sup_blur']) != float and params['voxel_sup_blur'][0] == '/'  :
        voxel_sup_blur = f[params['voxel_sup_blur']][()]
    else :
        voxel_sup_blur = params['voxel_sup_blur']
    
    # voxel_sup_blur_frac support
    if params['voxel_sup_blur_frac'] is None :
        voxel_sup_blur_frac = None
    elif type(params['voxel_sup_blur_frac']) != float and params['voxel_sup_blur_frac'][0] == '/'  :
        voxel_sup_blur_frac = f[params['voxel_sup_blur_frac']][()]
    else :
        voxel_sup_blur_frac = params['voxel_sup_blur_frac']
    
    # support update frequency
    if params['support_update_freq'] is None :
        support_update_freq = None
    elif type(params['support_update_freq']) != int and params['support_update_freq'][0] == '/'  :
        support_update_freq = f[params['support_update_freq']][()]
    else :
        support_update_freq = params['support_update_freq']

    # fixed support
    if params['support'] is None or params['support'] is False :
        support = None
    else :
        support = f[params['support']][()]
        
    # Bragg weighting
    if params['bragg_weighting'] is None or params['bragg_weighting'] is False :
        bragg_weighting = None
    else :
        bragg_weighting = f[params['bragg_weighting']][()]

    # Diffuse weighting
    if params['diffuse_weighting'] is None or params['diffuse_weighting'] is False :
        diffuse_weighting = None
    else :
        diffuse_weighting = f[params['diffuse_weighting']][()]

    # Unit cell parameters
    if type(params['unit_cell']) != int and params['unit_cell'][0] == '/'  :
        unit_cell = f[params['unit_cell']][()]
    else :
        unit_cell = params['unit_cell']
    
    
    # make the mapper
    #################
    #solid_unit = support * np.random.random(f[params['data']].shape) + 0J
    I0 = f[params['data']][()]
    mapper = maps.Mapper_ellipse(f[params['data']][()], 
                                 Bragg_weighting   = bragg_weighting, 
                                 diffuse_weighting = diffuse_weighting, 
                                 solid_unit        = solid_unit,
                                 voxels            = voxels,
                                 voxel_sup_blur    = voxel_sup_blur,
                                 voxel_sup_blur_frac = voxel_sup_blur_frac,
                                 overlap           = params['overlap'],
                                 support           = support,
                                 support_update_freq = support_update_freq,
                                 unit_cell         = unit_cell,
                                 space_group       = params['space_group'],
                                 alpha             = params['alpha'],
                                 dtype             = params['dtype']
                                 )
    # testing
    #########
    """
    import maps as maps_cpu
    mapper_cpu = maps_cpu.Mapper_ellipse(f[params['data']][()], 
                                 Bragg_weighting   = bragg_weighting, 
                                 diffuse_weighting = diffuse_weighting, 
                                 solid_unit        = solid_unit,
                                 voxels            = voxels,
                                 voxel_sup_blur    = voxel_sup_blur,
                                 voxel_sup_blur_frac = voxel_sup_blur_frac,
                                 overlap           = params['overlap'],
                                 support           = support,
                                 support_update_freq = support_update_freq,
                                 unit_cell         = unit_cell,
                                 space_group       = params['space_group'],
                                 alpha             = params['alpha'],
                                 dtype             = params['dtype']
                                 )
    f.close()


    m20 = mapper_cpu.modes.copy()
    m2  = m20.copy()
    m0 = mapper.modes.copy()
    m  = m0.copy()
    mapper.fftM3Dc(m, m)
    m  = m.get()
    
    print('cpu == gpu?', np.allclose(m, m2))
    print('cpu -  gpu:', np.sum(np.abs(m - m2)**2))
    m2 = np.fft.ifftn(m2, axes=(1,2,3))
    m  = np.fft.ifftn(m, axes=(1,2,3))
    print('cpu -  gpu:', np.sum(np.abs(m - m2)**2))
    
    I  = mapper.Imap(m0.copy()).get()
    print('gpu: I - I2:', np.sum(np.abs(I0 - I)**2))
    
    I  = mapper_cpu.Imap(mapper_cpu.modes)
    print('cpu: I - I2:', np.sum(np.abs(I0 - I)**2))
    
    Ig  = mapper.Imap(mapper.Pmod(m0.copy())).get()
    print('gpu: I - I2:', np.sum(np.abs(I0 - Ig)**2))
    
    Ic  = mapper.Imap(mapper.Pmod(m0.copy())).get()
    print('cpu - gpu?', np.sum( np.abs(np.fft.fftn(m0.get(), axes=(1,2,3)), m20)**2 ))
    #Ic  = mapper_cpu.Imap(mapper_cpu.Pmod(np.fft.fftn(m0.get(), axes=(1,2,3))))
    print('cpu: I - I2:', np.sum(np.abs(I0 - Ic)**2))




    I2 = mapper_cpu.Imap(mapper_cpu.modes)
    I  = mapper.Imap(mapper.modesg).get()
    print('I - I2:', np.sum(np.abs(I - I2)**2))
    maps.pycuda.driver.stop_profiler()

    m = mapper.Psup(m0)
    print(np.sum(m.get(), axis=(1,2,3)))
    #mapper.fftM3Dc(m, m)
    m2 = np.fft.ifftn(mapper_cpu.Psup(mapper_cpu.modes), axes=(1,2,3))
    print('cpu -  gpu:', np.sum(np.abs(m.get() - m2)**2))

    m  = mapper.Pmod(m0.copy())
    m2 = mapper_cpu.Pmod(m20)
    m3 = np.fft.ifftn(m2, axes=(1,2,3))
    #mapper.fftM4Dc(m, m0)
    #mapper.fftM4Dc(m, m, 1)
    #m2 = np.fft.fftn(m20, axes=(0,))
    #m2 = np.fft.ifftn(m2)
    print('cpu -  gpu:', np.sum(np.abs(m.get() - m3)**2))
    
    I2 = mapper_cpu.Imap(m2)
    I  = mapper.Imap(m).get()
    print('I - I2:', np.sum(np.abs(I - I2)**2))
    """
    # phase
    #######
    O, mapper, eMod, eCon, info = phase(mapper, params['iters'], params['beta'])
    
    # calculate the fidelity if we have the ground truth
    ####################################################
    if params['input_file'] is None :
        f = h5py.File(args.filename)
    else :
        f = h5py.File(params['input_file'])
    
    #if '/forward_model/solid_unit' in f:
    #    fids, fids_trans = [], []
    #    #O = h5py.File('duck_both/duck_both.h5.bak')['/phase/solid_unit'][()]
    #    syms = mapper.sym_ops.solid_syms_real(O, mapper.modes).get()
    #    for o in syms:
    #        fid, fid_trans = fidelity.calculate_fidelity(f['/forward_model/solid_unit'][()], O)
    #        fids.append(fid)
    #        fids_trans.append(fid_trans)
    #    i         = np.argmin(np.array(fids_trans))
    #    info['fidelity'] = fids[i]
    #    info['fidelity_trans'] = fids_trans[i]
    
    # output
    ########
    if params['output_file'] is not None and params['output_file'] is not False :
        filename = params['output_file']
    else :
        filename = args.filename
    
    outputdir = os.path.split(os.path.abspath(filename))[0]

    # mkdir if it does not exist
    if not os.path.exists(outputdir):
        os.makedirs(outputdir)

    filename2 = os.path.join(outputdir, 'O_'+str(np.random.randint(10000, 100000))+'.h5')
    print('writing to:', filename2)
    ff = h5py.File(filename2)
    # solid unit
    key = 'solid_unit'
    if key in ff :
        del ff[key]
    ff[key] = O
    # eMod
    key = 'eMod'
    if key in ff :
        del ff[key]
    ff[key] = np.array(info['eMod'])
    # eMod
    key = 'eCon'
    if key in ff :
        del ff[key]
    ff[key] = np.array(info['eCon'])
    ff.close()

    
    print('writing to:', filename)
    f = h5py.File(filename)
    
    group = '/phase'
    if group not in f:
        f.create_group(group)
    
    # solid unit
    key = group+'/solid_unit'
    if key in f :
        del f[key]
    f[key] = O
    
    # real-space crystal
    key = group+'/crystal'
    if key in f :
        del f[key]
    #f[key] = mapper.sym_ops.solid_to_crystal_real(O)
    
    del info['eMod']
    del info['eCon']
    info['eMod'] = eMod
    info['eCon'] = eCon
    # everything else
    for key, value in info.items():
        if value is None :
            continue 
        
        h5_key = group+'/'+key
        if h5_key in f :
            del f[h5_key]
        
        try :
            print('writing:', h5_key, type(value))
            f[h5_key] = value
        
        except Exception as e :
            print('could not write:', h5_key, ':', e)
        
    f.close() 
    
    # copy the config file
    ######################
    try :
        import shutil
        shutil.copy(args.config, outputdir)
    except Exception as e :
        print(e)