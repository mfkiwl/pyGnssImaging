#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Oct 26 12:12:41 2017

@author: Sebastijan Mrak <smrak@bu.edu>
"""

import numpy as np
import os
import numpy.ma as ma
import datetime
import h5py
import ephem
import glob
import multiprocessing  
import subprocess
import yaml
import scipy.ndimage
import matplotlib.pyplot as plt
from mpl_toolkits.basemap import Basemap
from pymap3d.coordconv3d import aer2geodetic
from scipy import interpolate
from argparse import ArgumentParser
from PIL import Image

YMLFN = ''
EUVDIR = '/home/smrak/Documents/eclipse/MapsSDOdisk300/'
# %% Util Functions
def getNeighbours(image,i,j):
    """
    Return an array of <=9 neighbour pixel of an image with a center at (i,j)
    """
    nbg = []
    for k in np.arange(i-1, i+2):
        for l in np.arange(j-1, j+2):
            try:
                nbg.append(image[k,l])
            except Exception as e:
                pass
    return np.array(nbg)

def filterMask(im,i,j, mask_size=3, ftype='mean'):
    """
    Return a filterd vaule of a pixel from the image im(i,j). Varaible mask size 
    and  filter type.
    TO DO: implement Gaussian filter
    """
    nbg = []
    for k in np.arange(i-1, i+mask_size-1):
        for l in np.arange(j-1, j+mask_size-1):
                try:
                    if np.isfinite(im[k,l]):
                        nbg.append(im[k,l])
                except Exception as e:
                    pass
    if ftype == 'mean':
        return np.mean(np.array(nbg))
    elif ftype == 'median':
        return np.median(np.array(nbg))

def imageFilter(im, mask_size=3, ftype='mean'):
    """
    Go throught the image anf filter it with a given type and mask size. It is necessary
    to filter the image like this due to scipy.im_filter sensetivity to NaN values.
    It is kidna slow, mak a C++ function?
    """
    im_filt = im.copy()
    for i in np.arange(0,im.shape[0]):
        for j in np.arange(0,im.shape[1]):
            im_filt[i,j] = filterMask(im,i,j, mask_size=mask_size, ftype=ftype)
    return im_filt
            
def fillPixels(im, N=1):
    """
    Fill in the dead pixels. If a dead pixel has a least 4 finite neighbour
    pixel, than replace the center pixel with a mean valuse of the neighbours
    """
    for n in range(N):
        for i in np.arange(0,im.shape[0]):
            for j in np.arange(0,im.shape[1]):
                # Check if th epixel is dead, i.e. empty
                if np.isnan(im[i,j]):
                    # Get its neighbours as a np array
                    nbg = getNeighbours(im,i,j)
                    # If there are at leas 4 neighbours, replace the value with a mean
                    if sum(np.isfinite(nbg)) >= 4:
                        ix = np.where(np.isfinite(nbg))[0]
                        avg = np.mean(nbg[ix])
                        im[i,j] = avg
    return im

def interpolateImage(im, xgrid=0, ygrid=0, res=1, method='cubic'):
    """
    Interpolate function, resample it with a new resolution and/or interpolate
    dead pixels. Use cubic, nearest or lienar methods.
    """
    im_mask = np.ma.masked_invalid(im)
    
    xd = abs(xgrid[0,0] - xgrid[-1,0]) / res * 1j
    yd = abs(ygrid[0,-1] - ygrid[0,0]) / res * 1j
    xgrid2, ygrid2 = np.mgrid[xgrid[0,0] : xgrid[-1,0] : xd, 
                              ygrid[0,-1] : ygrid[0,0] : yd]
    
    x1 = xgrid[~im_mask.mask]
    y1 = ygrid[~im_mask.mask]
    newarr = im_mask[~im_mask.mask]
    
    GD = interpolate.griddata((x1,y1), newarr.ravel(), (xgrid2, ygrid2), method=method)
    
    return xgrid2, ygrid2, GD

def makeGrid(ylim=[25,50],xlim=[-110,-80],res=0.5):
    """
    Make a grid for an image with a given boundaries and resolution
    """
    xd = abs(xlim[0] - xlim[1]) / res * 1j
    yd = abs(ylim[0] - ylim[1]) / res * 1j
    xgrid, ygrid = np.mgrid[xlim[0]:xlim[1]:xd, ylim[0]:ylim[1]:yd]
    z = np.nan*np.zeros((xgrid.shape[0], xgrid.shape[1]))
    
    return xgrid, ygrid, z

def returnIndex(x, i, delta):
    """
    Return right index for a time array from a minor array with a sapn of
    i pm delta.
    """
    if sum(sum(np.isfinite(x))) > 0:
        idval = np.where(np.isfinite(x))[0][0]
        lst = np.arange(i-delta,i+delta,1)
        ix = lst[idval]
        return ix
    else:
        return np.nan
    
def getImageIndex(x, y, xlim, ylim, xgrid, ygrid):
    """
    find and return a pixel location on the image to map the LOS value. find the
    pixel which minimizes the distance in x and y direction
    """
    if x > xlim[0] and x < xlim[1] and y > ylim[0] and y < ylim[1]:
        idy = abs(ygrid[0,:] - y).argmin()
        idx = abs(xgrid[:,0] - x).argmin()
    else:
        idy = np.nan
        idx = np.nan
    return idx, idy

def checkImagePath(save_dir):
    if not os.path.exists(save_dir):
        subprocess.call('mkdir {}'.format(save_dir), shell=True)
# %% Plotting Utils
def getMoonPosition(date, ipp_alt=300):
    """
    Sebasitjan Mrak
    """
    moon = ephem.Moon()
    obs = ephem.Observer()
    obs.date = date
    boston = ephem.city('Boston')
    obs.lat = boston.lat
    obs.long = boston.long
    obs.elev = boston.elev
    moon.compute(obs)

    r = ipp_alt / np.sin(moon.alt)
    
    lla_vector = np.array(aer2geodetic(np.rad2deg(moon.az), np.rad2deg(moon.alt), r, 
                                       np.rad2deg(obs.lat), np.rad2deg(obs.lon), np.rad2deg(obs.elev)))
    return lla_vector

def getEUVMaskCoordinates(latlim=[-89.5,89.5],lonlim=[-180,180],nlat=180,nlon=360):
    xgrid, ygrid = np.mgrid[lonlim[0]:lonlim[1]:nlon*1j, latlim[0]:latlim[1]:nlat*1j]
    return xgrid,ygrid

def getEUVMask(time,nlat=180,nlon=360):
    """
    I: time in posix
    """
    global EUVDIR
    xgrid, ygrid = getEUVMaskCoordinates(nlat=nlat, nlon=nlon)
    npts = nlat*nlon
    #Import EUV mask files
    flist = np.sort(glob.glob(EUVDIR+'*.bin'))
    Tframe_full = datetime.datetime.utcfromtimestamp(time)
    if int(Tframe_full.strftime('%H')) >= 16 and int(Tframe_full.strftime('%H')) < 22:
        # find right filename extension
        TframeHM = Tframe_full.strftime('%H%M')
        flist = np.sort(glob.glob(EUVDIR+'*'+TframeHM+'.bin'))
        # Get Mask
        data = np.fromfile(flist[0],count=npts, dtype=np.float32).reshape((nlat,nlon))
        return xgrid, ygrid, data
    else:
        return 0, 0, 0

def plotTotalityMask(m,time):
    """
    Get the totality coordinates. Remark: this is a totality on the ground!
    Reference: NASA web page
    """
    totality_path = h5py.File('/home/smrak/Documents/eclipse/totality.h5', 'r')
    lat = totality_path['path/center_lat'].value
    lon = totality_path['path/center_lon'].value
    Tt = totality_path['path/time'].value
    
    idt = abs(Tt - time).argmin()
    if abs(Tt - time).min() < 500:
        x,y = m(lon[idt], lat[idt])
        
        m.scatter(x, y, s=120, facecolors='none', edgecolors='w', linewidth=2, alpha=1)
#        m.scatter(x, y, s=1500, facecolors='none', edgecolors='k', linewidth=0.5, linestyle='--')
#        m.scatter(x, y, s=15000, facecolors='none', edgecolors='k', linewidth=0.5, linestyle='--')
#        m.scatter(x, y, s=60000, facecolors='none', edgecolors='k', linewidth=0.5, linestyle='--')
#        m.scatter(x, y, s=200000, facecolors='none', edgecolors='k', linewidth=0.5, linestyle='--')
#        m.scatter(x, y, s=250000, facecolors='none', edgecolors='k', linewidth=0.5, linestyle='--')
#        m.scatter(x, y, s=300000, facecolors='none', edgecolors='k', linewidth=0.5, linestyle='--')
    return m

def plotMap(latlim=[20, 65], lonlim=[-160, -70], center=[39, -86],
            parallels=[20,30,40,50], 
            meridians = [-120,-110, -100, -90, -80,-70],
            epoto=False, totality=True, totality_mask=False,time=None):
    """
    Plot the map and return handlers of the figure
    """
    (fig,ax) = plt.subplots(1,1,facecolor='w', figsize=(12,8))
    m = Basemap(lat_0=40, lon_0=-95,llcrnrlat=latlim[0],urcrnrlat=latlim[1],
                llcrnrlon=lonlim[0],urcrnrlon=lonlim[1],
                projection='merc')#, resolution='i', ax=ax)
    m.drawmapboundary(fill_color='grey')
    
    m.drawcoastlines(color='#006600')
    m.drawstates(color='#006600')
    m.drawcountries(color='#006600')
    if epoto == True:
        m.etopo()
        
    if time is not None:
        title = datetime.datetime.utcfromtimestamp(time)
        ax.set_title(title)
    
    if totality:
        totality_path = h5py.File('/home/smrak/Documents/eclipse/totality.h5', 'r')
        north_lat = np.array(totality_path['path/north_lat'])
        north_lon = np.array(totality_path['path/north_lon'])
        south_lat = np.array(totality_path['path/south_lat'])
        south_lon = np.array(totality_path['path/south_lon'])
    
        X1,Y1 = m(north_lon, north_lat)
        X2,Y2 = m(south_lon, south_lat)
        m.plot(X1,Y1, c='b')
        m.plot(X2,Y2, c='b')
    if totality_mask:
        m = plotTotalityMask(m,time)
    return fig, ax, m

def plotImage(x,y,z, time=0, clim=[], cmap='jet', save_dir='', raw_image=False):
    """
    Plot just an image
    """
    fig = plt.figure(figsize=(12,12))
    Zm = ma.masked_where(np.isnan(z),z)
    plt.pcolormesh(x, y, Zm, cmap=cmap)
    plt.clim(clim)
    plt.colorbar()
    if raw_image:
        checkImagePath(save_dir+'tif')
        im = Image.fromarray(Zm)
        im.save('{}tif/{}.tif'.format(save_dir,time))
    else:
        title = datetime.datetime.utcfromtimestamp(time)
        plt.title(title)
        plt.savefig('{}{}.png'.format(save_dir,time))
    return fig

def plotEUVMask(m, time, euv_gradient=True, cmap='bone', lw=0.9):
    try:
        xgrid, ygrid, data = getEUVMask(time)
        x,y = m(xgrid, ygrid)
        if euv_gradient:
            data = abs(scipy.ndimage.filters.laplace(data))
            levels = np.linspace(0.006,.025,7)
#            levels = [-.02, -.016,-.012, -.008, -.005, .005, .008, .012, .016, 0.020]
#            levels = [.0055, .008, .012, .018, .025]
            m.contour(x,y,data.T, levels, cmap=cmap)
        else:
            levels = np.linspace(0,1,60)
            m.contour(x,y,data.T, levels, colors='w', linewidths=lw)
    except:
        pass
    return m
    
def plotMoon(m, time):
    lla = getMoonPosition(datetime.datetime.utcfromtimestamp(time))
    x,y = m(lla[1], lla[0])
    m.scatter(x, y, s=120, facecolors='none', edgecolors='m', linewidth=2)
    return m

def plotScatterTEC(lat=[], lon=[], z=[], ms=10, color='k', alpha=0.6,
                   ax=None, m=None, clim=None, cmap='jet', cbar=False,
                   time=0, euv_mask=False, euv_gradient=False, lw=0.5):
    if (lat.shape[0] > 0) and (lon.shape[0] > 0):
        x,y = m(lon, lat)
        a = m.scatter(x, y, c=z, cmap=cmap, alpha=alpha, s=ms)
        a.set_clim(clim)
        if euv_mask:
            m = plotEUVMask(m, time, euv_gradient=euv_gradient, lw=lw)
        if cbar == True:
            plt.colorbar(a)
    return ax, m

def plotImageMap(fig,m,ax, xgrid,ygrid,z,time=0,clim=[],cmap='jet',
                 save_dir='', totality=False, raw_image=False, euv_mask=False,
                 moon=False, euv_gradient=False):
    """
    Plot the image on the basemap
    """
    title = datetime.datetime.utcfromtimestamp(time)
    ax.set_title(title)
    x,y = m(xgrid, ygrid)
    Zm = ma.masked_where(np.isnan(z),z)
    gca = m.pcolormesh(x,y,Zm, cmap='jet')
    # If you want to plot totality and concentric circles?
    if totality:
        m = plotTotalityMask(m, time)
    if euv_mask:
        m = plotEUVMask(m, time, euv_gradient=euv_gradient)
    if moon:
        m = plotMoon(m, time)
    gca.set_clim(clim)
    plt.colorbar(gca)
    if save_dir is not None:
        checkImagePath(save_dir)
        plt.savefig('{}{}.png'.format(save_dir,time))
    if raw_image:
        checkImagePath(save_dir+'tif')
        im = Image.fromarray(Zm)
        im.save('{}tif/{}.tif'.format(save_dir,time))
    
    return fig,m,ax

# %% Gather the data for a single frame
def singleImage(i):
    """
    Produse a single image given a HDF data file. An inpit 'i' is an argumnet for
    a given time stamp.
    """
    stream = yaml.load(open(YMLFN, 'r'))
    fname = stream.get('hdffilename')
    f = h5py.File(fname, 'r')
    t = f['obstimes'].value
    
    ylimmap = stream.get('ylimmap')
    xlimmap = stream.get('xlimmap')
    ylim = stream.get('ylim')
    xlim = stream.get('xlim')
    
    im_resolution = stream.get('im_resolution')
    save_dir = stream.get('save_dir')
    delta = stream.get('delta')
    image_interpolate = stream.get('image_interpolate')
    interpolate_method = stream.get('interpolate_method')
    interpolate_resolution = stream.get('interpolate_resolution')
    fillpixel_iter = stream.get('fill_pixel_iter')
    image_mask_size = stream.get('image_mask_size')
    image_filter_type = stream.get('image_filter_type')
    clim = stream.get('clim')
    totality_mask = stream.get('totality')
    euv_mask = stream.get('euv_mask')
    euv_gradient = stream.get('euv_gradient')
    eclipse = stream.get('eclipse')
    scatter_plot = stream.get('scatter_plot')
    basemap_image = stream.get('basemap_image')
    raw_image = stream.get('raw_image')
    moon = stream.get('moon')
    
    # Create an image grids
    xgrid, ygrid, im = makeGrid(ylim=ylim, xlim=xlim, res=im_resolution)
    if scatter_plot:
        c = 0
        # Plot the background basemap 
        fig, ax, m = plotMap(lonlim=xlimmap, latlim=ylimmap, totality=eclipse, time=t[i])
    for k in f.keys():
        if k != 'obstimes':
            # find index of the closest entry in the array to the given time index.
            # Search in the range +- delta around the given time index
            tmp = f[k+'/lat'][i-delta : i+delta]
            idt = returnIndex(tmp, i, delta)
            # If idt index exists (non empty)
            if np.isfinite(idt):
                # Retreive the data from a file
                lat = f[k+'/lat'][idt]
                lon = f[k+'/lon'][idt]
                residual = f[k+'/res'][idt]
                if scatter_plot:
                    try:
                        if c == 0:
                            c += 1
                            ax, m = plotScatterTEC(lat=lat, lon=lon, z=residual, 
                                                   ax=ax, m=m, clim=clim, ms=3, 
                                                   cmap='jet', euv_mask=euv_mask, cbar=True,
                                                   time=t[i], euv_gradient=euv_gradient)
                        else:
                            ax, m = plotScatterTEC(lat=lat, lon=lon, z=residual, 
                                                   ax=ax, m=m, clim=clim, ms=3, 
                                                   cmap='jet', cbar=False)
                    except:
                        pass
                else:
                    # Find the image index (pixel) that correcponds to the LOS value
                    for j in np.where(np.isfinite(residual))[0]:
                        idx, idy = getImageIndex(x = lon[j], y = lat[j],
                                                 xlim = xlim, ylim = ylim,
                                                 xgrid = xgrid, ygrid = ygrid)
                        # If image indexes are valid
                        if np.isfinite(idx) and np.isfinite(idy):
                            # Assign the value to the pixel
                            if np.isnan(im[idx,idy]):
                                im[idx,idy] = residual[j]
                            # If this is not the first value to assign, assign a
                            # mean of both values
                            else:
                                im[idx,idy] = (im[idx,idy] + residual[j]) / 2
    if not scatter_plot:
        # Plot the background basemap 
        fig, ax, m = plotMap(lonlim=xlimmap, latlim=ylimmap, totality=eclipse)
        # Raw image Done. Now first fill the empty pixel N-times
        if fillpixel_iter > 0:
            im = fillPixels(im, N=fillpixel_iter)
        # Reinterpolate the image? witah a new resolution and a given interpolation method
        if image_interpolate:
            xgrid, ygrid, im = interpolateImage(im, xgrid, ygrid,res=interpolate_resolution, method=interpolate_method)
        # Filter the image with a median or mean filter with a given size of the filter mask
        if image_filter_type is not None:
            im = imageFilter(im, mask_size=image_mask_size, ftype=image_filter_type)
        if basemap_image:
            # Plot the Image
            fig, m, ax = plotImageMap(fig,m,ax,xgrid,ygrid,im,clim=clim,cmap='jet',time=t[i],
                             save_dir=save_dir, totality=totality_mask, euv_mask=euv_mask, 
                             moon=moon, euv_gradient=euv_gradient)

        if raw_image:
            fig = plotImage(xgrid,ygrid,im,time=t[i],clim=clim, save_dir=save_dir,
                            raw_image=raw_image)
            # Close the figure handler
            plt.close(fig)
    else:
        if totality_mask:
            plotTotalityMask(m,t[i])
        checkImagePath(save_dir)
        plt.savefig('{}{}.png'.format(save_dir,t[i]))

# %% Parallel handler
def runImaging(f, iterate):
    for i in iterate:
        p = multiprocessing.Process(target=singleImage, args=(i,))
        p.start()
        p.join(360) # Timeout = 1 min
# %% Main program, get the parameters and start the imaging script
def main(config_file=None, datafile='', svdir='', N=False):
    global YMLFN
    # Create a sample config file if there is no template
    if config_file is None:
        if svdir == '':
            svdir = 'images/'
        if datafile == '':
            datafile = '/media/smrak/Eclipse2017/Eclipse/hdf/linecut_trial_130_60_imode2_ed1000_14.h5'
        
        decimate = 30
        delta = int(decimate/2)
        im_resolution = 0.5
        interpolate_resolution = 0.25
        
        ylim=[22,50]
        xlim=[-125,-65]
        clim = [-0.2, 0.2]
        
        fill_pixel_iter = 3
        image_interpolate = False
        interpolate_method = 'nearest'
        image_filter_type = 'median'
        image_mask_size = 3
        
        skipimage = 3
        
        totality = False
        eclipse = False
        basemap_image = True
        scatter_plot = False
        raw_image = False
        #Make a sample yaml cfg file
        YMLFN = 'plottinparams.yaml'
        datadict = {'hdffilename': datafile, 
                    'decimate': decimate,
                    'xlim':xlim, 
                    'ylim':ylim, 
                    'im_resolution':im_resolution,
                    'delta': delta,
                    'skip_image': skipimage,
                    'save_dir': svdir, 
                    'fill_pixel_iter': fill_pixel_iter,
                    'image_interpolate': image_interpolate,
                    'interpolate_method': interpolate_method,
                    'interpolate_resolution': interpolate_resolution,
                    'image_filter_type': image_filter_type,
                    'image_mask_size': image_mask_size,
                    'clim': clim,
                    'basemap_image': basemap_image,
                    'scatter_plot': scatter_plot,
                    'raw_image': raw_image,
                    'eclipse': eclipse,
                    'totality': totality}
        with open(YMLFN, 'w') as outfile:
            yaml.dump(datadict, outfile, default_flow_style=True) 
    else:
        YMLFN = config_file
        stream = yaml.load(open(config_file, 'r'))
        decimate = stream.get('decimate')
        skipimage = stream.get('skip_image')
        datafile = stream.get('hdffilename')
    
    # If the cfg file is given, read it
    f = h5py.File(datafile, 'r')
    # Get the obseration time boundaries
    timearray = f['obstimes'].value
    # Crate an itarate array with indexes
    iterate = np.arange(int(decimate), timearray.shape[0]-decimate, decimate*skipimage)
    # Plot only a given N first frames from the file?
    if N != False:
        runImaging(datafile,iterate[:int(N)])
    # Plot them all!
    else:
        runImaging(datafile,iterate)
    
if __name__ == '__main__':
    
    p = ArgumentParser()
    p.add_argument('-d', "--data_file", help='path to the HDF data file',
                   default='', type=str)
    p.add_argument('-c', "--cfg_yaml_file", help='path to the configuration file',
                   default=None)
    p.add_argument('-s', "--save_directory", help='path for directory to save images',
                   default='', type=str)
    p.add_argument('--Nimage', "--number_of_images", help='Plot just a given number of images',
                   default=False)
   
    P = p.parse_args()
    # Run
    main(config_file=P.cfg_yaml_file, datafile=P.data_file,svdir=P.save_directory, N=P.Nimage)
