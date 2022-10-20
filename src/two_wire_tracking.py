#!/usr/bin/env python

import matplotlib.pyplot as plt
import rospy
import ros_numpy
from sensor_msgs.msg import PointCloud2, PointField, Image
import sensor_msgs.point_cloud2 as pcl2
import std_msgs.msg

import struct
import time
import cv2
import numpy as np

import time
import pickle as pkl

import message_filters
from sklearn.neighbors import NearestNeighbors
import open3d as o3d

# temp
intersection = 18
# intersection = 15

def pt2pt_dis_sq(pt1, pt2):
    return np.sum(np.square(pt1 - pt2))

def register(pts, M, mu=0, max_iter=10):

    # initial guess
    X = pts.copy()
    Y = np.vstack((np.arange(0, 0.1, (0.1/M)), np.zeros(M), np.zeros(M))).T
    if len(pts[0]) == 2:
        Y = np.vstack((np.arange(0, 0.1, (0.1/M)), np.zeros(M))).T
    s = 1
    N = len(pts)
    D = len(pts[0])

    def get_estimates (Y, s):

        # construct the P matrix
        P = np.sum((X[None, :, :] - Y[:, None, :]) ** 2, axis=2)

        c = (2 * np.pi * s) ** (D / 2)
        c = c * mu / (1 - mu)
        c = c * M / N

        P = np.exp(-P / (2 * s))
        den = np.sum(P, axis=0)
        den = np.tile(den, (M, 1))
        den[den == 0] = np.finfo(float).eps
        den += c

        P = np.divide(P, den)  # P is M*N
        Pt1 = np.sum(P, axis=0)  # equivalent to summing from 0 to M (results in N terms)
        P1 = np.sum(P, axis=1)  # equivalent to summing from 0 to N (results in M terms)
        Np = np.sum(P1)
        PX = np.matmul(P, X)

        # get new Y
        P1_expanded = np.full((D, M), P1).T
        new_Y = PX / P1_expanded

        # get new sigma2
        Y_N_arr = np.full((N, M, 3), Y)
        Y_N_arr = np.swapaxes(Y_N_arr, 0, 1)
        X_M_arr = np.full((M, N, 3), X)
        diff = Y_N_arr - X_M_arr
        diff = np.square(diff)
        diff = np.sum(diff, 2)
        new_s = np.sum(np.sum(P*diff, axis=1), axis=0) / (Np*D)

        return new_Y, new_s

    prev_Y, prev_s = Y, s
    new_Y, new_s = get_estimates(prev_Y, prev_s)
    # it = 0
    tol = 0.0
    
    for it in range (max_iter):
        prev_Y, prev_s = new_Y, new_s
        new_Y, new_s = get_estimates(prev_Y, prev_s)

    # print(repr(new_x), new_s)
    return new_Y, new_s

# assuming Y is sorted
# for now, assume each wire has the same number of nodes
# k -- going left for k indices, going right for k indices. a total of 2k neighbors.
def get_nearest_indices (k, Y, idx):
    if idx < intersection:
        if idx - k < 0:
            # use more neighbors from the other side?
            # indices_arr = np.append(np.arange(0, idx, 1), np.arange(idx+1, idx+k+1+np.abs(idx-k)))
            indices_arr = np.append(np.arange(0, idx, 1), np.arange(idx+1, idx+k+1))
            return indices_arr
        elif idx + k >= intersection:
            last_index = intersection - 1
            # use more neighbots from the other side?
            # indices_arr = np.append(np.arange(idx-k-(idx+k-last_index), idx, 1), np.arange(idx+1, last_index+1, 1))
            indices_arr = np.append(np.arange(idx-k, idx, 1), np.arange(idx+1, last_index+1, 1))
            return indices_arr
        else:
            indices_arr = np.append(np.arange(idx-k, idx, 1), np.arange(idx+1, idx+k+1, 1))
            return indices_arr
    else:
        if idx - k < intersection:
            # use more neighbors from the other side?
            # indices_arr = np.append(np.arange(intersection, idx, 1), np.arange(idx+1, idx+k+1+np.abs(idx-k-intersection)))
            indices_arr = np.append(np.arange(intersection, idx, 1), np.arange(idx+1, idx+k+1))
            return indices_arr
        elif idx + k >= len(Y):
            last_index = len(Y) - 1
            # use more neighbors from the other side?
            # indices_arr = np.append(np.arange(idx-k-(idx+k-last_index), idx, 1), np.arange(idx+1, last_index+1, 1))
            indices_arr = np.append(np.arange(idx-k, idx, 1), np.arange(idx+1, last_index+1, 1))
            return indices_arr
        else:
            indices_arr = np.append(np.arange(idx-k, idx, 1), np.arange(idx+1, idx+k+1, 1))
            return indices_arr

def calc_LLE_weights (k, X):
    W = np.zeros((len(X), len(X)))
    for i in range (0, len(X)):
        indices = get_nearest_indices(int(k/2), X, i)

        # # test
        # print(i, indices)

        xi, Xi = X[i], X[indices, :]
        component = np.full((len(Xi), len(xi)), xi).T - Xi.T
        Gi = np.matmul(component.T, component)
        # Gi might be singular when k is large
        try:
            Gi_inv = np.linalg.inv(Gi)
        except:
            epsilon = 0.00001
            Gi_inv = np.linalg.inv(Gi + epsilon*np.identity(len(Gi)))
        wi = np.matmul(Gi_inv, np.ones((len(Xi), 1))) / np.matmul(np.matmul(np.ones(len(Xi),), Gi_inv), np.ones((len(Xi), 1)))
        W[i, indices] = np.squeeze(wi.T)

    return W

def indices_array(n):
    r = np.arange(n)
    out = np.empty((n,n,2),dtype=int)
    out[:,:,0] = r[:,None]
    out[:,:,1] = r
    return out

# test
# trying to give less penalty to nodes far away (index wise)
total_num_of_nodes = 31
coeff = indices_array(total_num_of_nodes)
coeff = np.abs(coeff[:, :, 0] - coeff[:, :, 1])

# normalize coeff
min_coeff = 1
# max_coeff = 1.0003
max_coeff = 1.0003**3
coeff = np.full(np.shape(coeff), min_coeff) + coeff / np.amax(coeff) * (max_coeff - min_coeff)

# different wires should never interfere
coeff[0:intersection, intersection:total_num_of_nodes] = 50
coeff[intersection:total_num_of_nodes, 0:intersection] = 50
# print(coeff)

def cpd_lle (X, Y_0, beta, alpha, k, gamma, mu, max_iter, tol):
# def cpd_lle (X, Y_0, beta, alpha, H, gamma, mu, max_iter, tol):

    # define params
    M = len(Y_0)
    N = len(X)
    D = len(X[0])

    # initialization
    # faster G calculation
    diff = Y_0[:, None, :] - Y_0[None, :,  :]
    diff = np.square(diff)
    diff = np.sum(diff, 2)
    G = np.exp(-diff / (2 * beta**2))

    # G[0:intersection, intersection:M] = 0
    # G[intersection:M, 0:intersection] = 0

    # test
    # G = G / coeff # * or / ?
    # G = np.exp(-diff / (2 * beta**2 * coeff**(1/3)))
    
    Y = Y_0.copy()

    # initialize sigma2
    (N, D) = X.shape
    (M, _) = Y.shape
    diff = X[None, :, :] - Y[:, None, :]
    err = diff ** 2
    sigma2 = np.sum(err) / (D * M * N)

    # get the LLE matrix
    L = calc_LLE_weights(k, Y_0)
    H = np.matmul((np.identity(M) - L).T, np.identity(M) - L)
    
    # loop until convergence or max_iter reached
    for it in range (0, max_iter):

        # faster P computation
        P = np.sum((X[None, :, :] - Y[:, None, :]) ** 2, axis=2)

        c = (2 * np.pi * sigma2) ** (D / 2)
        c = c * mu / (1 - mu)
        c = c * M / N

        P = np.exp(-P / (2 * sigma2))
        den = np.sum(P, axis=0)
        den = np.tile(den, (M, 1))
        den[den == 0] = np.finfo(float).eps
        den += c

        P = np.divide(P, den)
        Pt1 = np.sum(P, axis=0)
        P1 = np.sum(P, axis=1)
        Np = np.sum(P1)
        PX = np.matmul(P, X)
    
        # M step
        A_matrix = np.matmul(np.diag(P1), G) + alpha * sigma2 * np.identity(M) + sigma2 * gamma * np.matmul(H, G)
        B_matrix = PX - np.matmul(np.diag(P1) + sigma2*gamma*H, Y_0)
        W = np.linalg.solve(A_matrix, B_matrix)

        # update sigma2
        T = Y_0 + np.matmul(G, W)
        trXtdPt1X = np.trace(np.matmul(np.matmul(X.T, np.diag(Pt1)), X))
        trPXtT = np.trace(np.matmul(PX.T, T))
        trTtdP1T = np.trace(np.matmul(np.matmul(T.T, np.diag(P1)), T))

        sigma2 = (trXtdPt1X - 2*trPXtT + trTtdP1T) / (Np * D)

        # update Y
        if pt2pt_dis_sq(Y, Y_0 + np.matmul(G, W)) < tol:
            Y = Y_0 + np.matmul(G, W)
            break
        else:
            Y = Y_0 + np.matmul(G, W)

    return Y

def find_closest (pt, arr):
    closest = arr[0].copy()
    min_dis = np.sqrt((pt[0] - closest[0])**2 + (pt[1] - closest[1])**2 + (pt[2] - closest[2])**2)
    idx = 0

    for i in range (0, len(arr)):
        cur_pt = arr[i].copy()
        cur_dis = np.sqrt((pt[0] - cur_pt[0])**2 + (pt[1] - cur_pt[1])**2 + (pt[2] - cur_pt[2])**2)
        if cur_dis < min_dis:
            min_dis = cur_dis
            closest = arr[i].copy()
            idx = i
    
    return closest, idx

def find_opposite_closest (pt, arr, direction_pt):
    arr_copy = arr.copy()
    opposite_closest_found = False
    opposite_closest = pt.copy()  # will get overwritten

    while (not opposite_closest_found) and (len(arr_copy) != 0):
        cur_closest, cur_index = find_closest (pt, arr_copy)
        arr_copy.pop (cur_index)

        vec1 = np.array(cur_closest) - np.array(pt)
        vec2 = np.array(direction_pt) - np.array(pt)

        # threshold: 0.05m
        if (np.dot (vec1, vec2) < 0) and (pt2pt_dis_sq(np.array(cur_closest), np.array(pt)) < 0.05**2):
            opposite_closest_found = True
            opposite_closest = cur_closest.copy()
            break
    
    return opposite_closest, opposite_closest_found

def sort_pts (pts_orig):

    start_idx = 5

    pts = pts_orig.copy()
    starting_pt = pts[start_idx].copy()
    pts.pop(start_idx)
    # starting point will be the current first point in the new list
    sorted_pts = []
    sorted_pts.append(starting_pt)

    # get the first closest point
    closest_1, min_idx = find_closest (starting_pt, pts)
    sorted_pts.append(closest_1)
    pts.pop(min_idx)

    # get the second closest point
    closest_2, found = find_opposite_closest(starting_pt, pts, closest_1)
    true_start = False
    if not found:
        # closest 1 is true start
        true_start = True
    # closest_2 is not popped from pts

    # move through the rest of pts to build the sorted pt list
    # if true_start:
    #   can proceed until pts is empty
    # if !true_start:
    #   start in the direction of closest_1, the list would build until one end is reached. 
    #   in that case the next closest point would be closest_2. starting that point, all 
    #   newly added points to sorted_pts should be inserted at the front
    while len(pts) != 0:
        cur_target = sorted_pts[-1]
        cur_direction = sorted_pts[-2]
        cur_closest, found = find_opposite_closest(cur_target, pts, cur_direction)

        if not found:
            print ("not found!")
            break

        sorted_pts.append(cur_closest)
        pts.remove (cur_closest)

    # begin the second loop that inserts new points at front
    if not true_start:
        # first insert closest_2 at front and pop it from pts
        sorted_pts.insert(0, closest_2)
        pts.remove(closest_2)

        while len(pts) != 0:
            cur_target = sorted_pts[0]
            cur_direction = sorted_pts[1]
            cur_closest, found = find_opposite_closest(cur_target, pts, cur_direction)

            if not found:
                print ("not found!")
                break

            sorted_pts.insert(0, cur_closest)
            pts.remove(cur_closest)

    return sorted_pts

saved = False
initialized = False
init_nodes = []
nodes = []
# H = []
cur_time = time.time()
def callback (rgb, depth, pc):
    global saved
    global initialized
    global init_nodes
    global nodes
    # global H
    global cur_time

    proj_matrix = np.array([[918.359130859375,              0.0, 645.8908081054688, 0.0], \
                            [             0.0, 916.265869140625,   354.02392578125, 0.0], \
                            [             0.0,              0.0,               1.0, 0.0]])

    # process rgb image
    cur_image = ros_numpy.numpify(rgb)
    # cur_image = cv2.cvtColor(cur_image.copy(), cv2.COLOR_BGR2RGB)
    hsv_image = cv2.cvtColor(cur_image.copy(), cv2.COLOR_RGB2HSV)

    # # test
    # cv2.imshow('img', cur_image)
    # cv2.waitKey(0) 
    # cv2.destroyAllWindows()

    # process depth image
    cur_depth = ros_numpy.numpify(depth)

    # process point cloud
    pc_data = ros_numpy.point_cloud2.pointcloud2_to_array(pc)
    cur_pc = ros_numpy.point_cloud2.get_xyz_points(pc_data)
    cur_pc = cur_pc.reshape((720, 1280, 3))

    # print('image_shape = ', np.shape(hsv_image))

    # color thresholding
    lower = (90, 100, 80)
    upper = (120, 255, 255)
    mask = cv2.inRange(hsv_image, lower, upper)
    mask = cv2.cvtColor(mask.copy(), cv2.COLOR_GRAY2BGR)
    # print('mask shape = ', np.shape(mask))

    # publish mask
    mask_img_msg = ros_numpy.msgify(Image, mask, 'rgb8')
    mask_img_pub.publish(mask_img_msg)

    mask = (mask/255).astype(int)

    filtered_pc = cur_pc*mask
    filtered_pc = filtered_pc[((filtered_pc[:, :, 0] != 0) | (filtered_pc[:, :, 1] != 0) | (filtered_pc[:, :, 2] != 0))]
    filtered_pc = filtered_pc[filtered_pc[:, 2] < 0.605]
    filtered_pc = filtered_pc[filtered_pc[:, 2] > 0.4]
    # print('filtered pc shape = ', np.shape(filtered_pc))

    # # save points
    # if not saved:
    #     username = 'ablcts18'
    #     folder = 'tracking/'
    #     f = open("/home/" + username + "/Research/" + folder + "ros_pc.json", 'wb')
    #     pkl.dump(filtered_pc, f)
    #     f.close()
    #     saved = True

    # downsample to 2.5%
    # filtered_pc = filtered_pc[::int(1/0.1)]

    # downsample with open3d
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(filtered_pc)
    downpcd = pcd.voxel_down_sample(voxel_size=0.007)
    filtered_pc = np.asarray(downpcd.points)
    # print('down sampled pc shape = ', np.shape(filtered_pc))

    # add color
    pc_rgba = struct.unpack('I', struct.pack('BBBB', 255, 40, 40, 255))[0]
    pc_rgba_arr = np.full((len(filtered_pc), 1), pc_rgba)
    filtered_pc_colored = np.hstack((filtered_pc, pc_rgba_arr)).astype('O')
    filtered_pc_colored[:, 3] = filtered_pc_colored[:, 3].astype(int)

    # filtered_pc = filtered_pc.reshape((len(filtered_pc)*len(filtered_pc[0]), 3))
    header.stamp = rospy.Time.now()
    converted_points = pcl2.create_cloud(header, fields, filtered_pc_colored)
    pc_pub.publish(converted_points)

    # register nodes
    if not initialized:
        # try two wires
        wire1_pc = filtered_pc[filtered_pc[:, 0] > 0]
        wire2_pc = filtered_pc[filtered_pc[:, 0] < 0]

        print('filtered wire 1 shape = ', np.shape(wire1_pc))
        print('filtered wire 2 shape = ', np.shape(wire2_pc))

        # # get nodes for wire 1
        # init_nodes_1, _ = register(wire1_pc, 15, mu=0, max_iter=50)
        init_nodes_1 = np.array([[-1.27009724e-01,  4.14825357e-04,  4.52871539e-01],
                                [-1.54898246e-01, -1.99959384e-02,  4.51123124e-01],
                                [-1.72412218e-01, -3.41579425e-02,  4.50719521e-01],
                                [-1.62303231e-01, -2.63667164e-02,  4.49721778e-01],
                                [-1.39986265e-01, -7.90766445e-03,  4.52218090e-01],
                                [-1.16063114e-01,  7.30732350e-03,  4.56451478e-01],
                                [-1.03287281e-01,  1.64191108e-02,  4.57034100e-01],
                                [-8.76353685e-02,  2.77012005e-02,  4.54915663e-01],
                                [-7.21464421e-02,  3.47317274e-02,  4.54974480e-01],
                                [-5.59613760e-02,  4.36247728e-02,  4.58797092e-01],
                                [-3.80835279e-02,  5.13719688e-02,  4.60949620e-01],
                                [-1.46462847e-02,  6.01458400e-02,  4.59085010e-01],
                                [ 1.53298123e-02,  7.06612495e-02,  4.60718526e-01],
                                [ 4.59158222e-02,  8.51427749e-02,  4.61482631e-01],
                                [ 7.29576712e-02,  1.03318306e-01,  4.63495959e-01],
                                [ 9.27155833e-02,  1.26644998e-01,  4.63692264e-01],
                                [ 1.03272507e-01,  1.53314484e-01,  4.63873842e-01],
                                [ 1.07863333e-01,  1.75858068e-01,  4.64742587e-01]])
        init_nodes_1 = np.array(sort_pts(init_nodes_1.tolist()))

        # add color
        init_nodes_1_rgba = struct.unpack('I', struct.pack('BBBB', 0, 0, 0, 255))[0]
        init_nodes_1_rgba_arr = np.full((len(init_nodes_1), 1), init_nodes_1_rgba)
        init_nodes_1_colored = np.hstack((init_nodes_1, init_nodes_1_rgba_arr)).astype('O')
        init_nodes_1_colored[:, 3] = init_nodes_1_colored[:, 3].astype(int)
        header.stamp = rospy.Time.now()
        converted_nodes_1 = pcl2.create_cloud(header, fields, init_nodes_1_colored)
        init_nodes_1_pub.publish(converted_nodes_1)

        # # get nodes for wire 2
        # init_nodes_2, _ = register(wire2_pc, 15, mu=0, max_iter=50)
        init_nodes_2 = np.array([[-0.04978539, -0.08826958,  0.45399044],
                                [-0.05717473, -0.0760752 ,  0.45591002],
                                [-0.06246264, -0.05427032,  0.45739881],
                                [-0.06930357, -0.03164733,  0.45798269],
                                [-0.07532243, -0.01169516,  0.45983623],
                                [-0.0812431 ,  0.00803333,  0.458365  ],
                                [-0.09329984,  0.05316729,  0.45860219],
                                [-0.09728898,  0.07534121,  0.4570974 ],
                                [-0.10369568,  0.12654829,  0.46100685],
                                [-0.11005815,  0.17377957,  0.46193915],
                                [-0.1065393 ,  0.15161074,  0.462138  ],
                                [-0.10014007,  0.10297371,  0.45662362],
                                [-0.08763537,  0.0277012 ,  0.45891566]])
        init_nodes_2 = np.array(sort_pts(init_nodes_2.tolist()))

        # add color
        init_nodes_2_rgba = struct.unpack('I', struct.pack('BBBB', 255, 255, 255, 255))[0]
        init_nodes_2_rgba_arr = np.full((len(init_nodes_2), 1), init_nodes_2_rgba)
        init_nodes_2_colored = np.hstack((init_nodes_2, init_nodes_2_rgba_arr)).astype('O')
        init_nodes_2_colored[:, 3] = init_nodes_2_colored[:, 3].astype(int)
        header.stamp = rospy.Time.now()
        converted_nodes_2 = pcl2.create_cloud(header, fields, init_nodes_2_colored)
        init_nodes_2_pub.publish(converted_nodes_2)

        init_nodes = np.vstack((init_nodes_1, init_nodes_2))

        # # get the LLE matrix
        # L = calc_LLE_weights(2, init_nodes)
        # H = np.matmul((np.identity(len(init_nodes)) - L).T, np.identity(len(init_nodes)) - L)
        initialized = True
        # header.stamp = rospy.Time.now()
        # converted_init_nodes = pcl2.create_cloud(header, fields, init_nodes)
        # init_nodes_pub.publish(converted_init_nodes)

    # cpd
    if initialized:
        nodes = cpd_lle(X=filtered_pc, Y_0 = init_nodes, beta=1, alpha=1, k=6, gamma=3, mu=0.05, max_iter=30, tol=0.00001)
        # nodes = cpd_lle(X=filtered_pc, Y_0 = init_nodes, beta=1, alpha=1, H=H, gamma=2, mu=0.05, max_iter=30, tol=0.00001)
        init_nodes = nodes
        # print("finished reg")

        nodes_1 = nodes[0:intersection]
        nodes_2 = nodes[intersection:len(nodes)]

        # add color
        nodes_1_rgba = struct.unpack('I', struct.pack('BBBB', 0, 0, 0, 255))[0]
        nodes_1_rgba_arr = np.full((len(nodes_1), 1), nodes_1_rgba)
        nodes_1_colored = np.hstack((nodes_1, nodes_1_rgba_arr)).astype('O')
        nodes_1_colored[:, 3] = nodes_1_colored[:, 3].astype(int)
        header.stamp = rospy.Time.now()
        converted_nodes_1 = pcl2.create_cloud(header, fields, nodes_1_colored)
        nodes_1_pub.publish(converted_nodes_1)
        # add color
        nodes_2_rgba = struct.unpack('I', struct.pack('BBBB', 255, 255, 255, 255))[0]
        nodes_2_rgba_arr = np.full((len(nodes_2), 1), nodes_2_rgba)
        nodes_2_colored = np.hstack((nodes_2, nodes_2_rgba_arr)).astype('O')
        nodes_2_colored[:, 3] = nodes_2_colored[:, 3].astype(int)
        header.stamp = rospy.Time.now()
        converted_nodes_2 = pcl2.create_cloud(header, fields, nodes_2_colored)
        nodes_2_pub.publish(converted_nodes_2)

        # test
        print(nodes_1[-1], nodes_2[0])

        # project and pub image
        nodes_h = np.hstack((nodes, np.ones((len(nodes), 1))))
        # proj_matrix: 3*4; nodes_h.T: 4*M; result: 3*M
        image_coords = np.matmul(proj_matrix, nodes_h.T).T
        us = (image_coords[:, 0] / image_coords[:, 2]).astype(int)
        vs = (image_coords[:, 1] / image_coords[:, 2]).astype(int)

        tracking_img = cur_image.copy()
        for i in range (0, intersection):
            # draw circle
            uv = (us[i], vs[i])
            cv2.circle(tracking_img, uv, 5, (0, 255, 0), -1)

            # draw line
            if i != (intersection-1):
                cv2.line(tracking_img, uv, (us[i+1], vs[i+1]), (0, 255, 0), 2)
        for i in range (intersection, len(nodes)):
            # draw circle
            uv = (us[i], vs[i])
            cv2.circle(tracking_img, uv, 5, (255, 0, 0), -1)

            # draw line
            if i != len(image_coords)-1:
                cv2.line(tracking_img, uv, (us[i+1], vs[i+1]), (255, 0, 0), 2)
        
        tracking_img_msg = ros_numpy.msgify(Image, tracking_img, 'rgb8')
        tracking_img_pub.publish(tracking_img_msg)

        print(time.time() - cur_time)
        cur_time = time.time()

if __name__=='__main__':
    rospy.init_node('test', anonymous=True)

    rgb_sub = message_filters.Subscriber('/camera/color/image_raw', Image)
    depth_sub = message_filters.Subscriber('/camera/aligned_depth_to_color/image_raw', Image)
    pc_sub = message_filters.Subscriber('/camera/depth/color/points', PointCloud2)

    # header
    header = std_msgs.msg.Header()
    header.stamp = rospy.Time.now()
    header.frame_id = 'camera_color_optical_frame'
    fields = [PointField('x', 0, PointField.FLOAT32, 1),
                PointField('y', 4, PointField.FLOAT32, 1),
                PointField('z', 8, PointField.FLOAT32, 1),
                PointField('rgba', 12, PointField.UINT32, 1)]
    pc_pub = rospy.Publisher ('/pts', PointCloud2, queue_size=10)

    init_nodes_1_pub = rospy.Publisher ('/init_nodes_1', PointCloud2, queue_size=10)
    init_nodes_2_pub = rospy.Publisher ('/init_nodes_2', PointCloud2, queue_size=10)

    nodes_1_pub = rospy.Publisher ('/nodes_1', PointCloud2, queue_size=10)
    nodes_2_pub = rospy.Publisher ('/nodes_2', PointCloud2, queue_size=10)

    tracking_img_pub = rospy.Publisher ('/tracking_img', Image, queue_size=10)
    mask_img_pub = rospy.Publisher('/mask', Image, queue_size=10)

    ts = message_filters.TimeSynchronizer([rgb_sub, depth_sub, pc_sub], 10)
    ts.registerCallback(callback)

    rospy.spin()