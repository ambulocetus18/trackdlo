#!/usr/bin/env python

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
        print(it)
        prev_Y, prev_s = new_Y, new_s
        new_Y, new_s = get_estimates(prev_Y, prev_s)

    # print(repr(new_x), new_s)
    return new_Y, new_s

def calc_LLE_weights (k, X):
    knn = NearestNeighbors(algorithm='auto', leaf_size=3, n_neighbors=k+1, p=2, radius=1.0)
    knn.fit(X)
    W = np.zeros((len(X), len(X)))
    for i in range (0, len(X)):
        indices = np.squeeze(knn.kneighbors(X[i].reshape(1, -1), return_distance=False))
        indices = indices[indices != i]
        xi, Xi = X[i], X[indices, :]
        component = np.full((k, len(xi)), xi).T - Xi.T
        Gi = np.matmul(component.T, component)
        # Gi might be singular when k is large
        try:
            Gi_inv = np.linalg.inv(Gi)
        except:
            epsilon = 0.00001
            Gi_inv = np.linalg.inv(Gi + epsilon*np.identity(len(Gi)))
        wi = np.matmul(Gi_inv, np.ones((k, 1))) / np.matmul(np.matmul(np.ones(k,), Gi_inv), np.ones((k, 1)))
        W[i, indices] = np.squeeze(wi.T)

    return W

def cpd (X, Y_0, beta, alpha, k, gamma, mu, max_iter, tol):

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

        if np.dot (vec1, vec2) < 0:
            opposite_closest_found = True
            opposite_closest = cur_closest.copy()
            break
    
    return opposite_closest, opposite_closest_found

def find_aligned_closest (pt, arr, direction_pt):
    arr_copy = arr.copy()
    aligned_closest_found = False
    aligned_closest = pt.copy()  # will get overwritten

    while (not aligned_closest_found) and (len(arr_copy) != 0):
        cur_closest, cur_index = find_closest (pt, arr_copy)
        arr_copy.pop (cur_index)
        if np.dot (np.array(direction_pt), np.array(cur_closest)) > 0:
            aligned_closest_found = True
            aligned_closest = cur_closest.copy()
    
    return aligned_closest, aligned_closest_found

def sort_pts (pts_orig):

    start_idx = 10

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
def callback (rgb, depth, pc):
    global saved
    global initialized
    global init_nodes
    global nodes

    proj_matrix = np.array([[918.359130859375,              0.0, 645.8908081054688, 0.0], \
                            [             0.0, 916.265869140625,   354.02392578125, 0.0], \
                            [             0.0,              0.0,               1.0, 0.0]])

    # process rgb image
    cur_image = ros_numpy.numpify(rgb)
    # cur_image = cv2.cvtColor(cur_image.copy(), cv2.COLOR_BGR2RGB)

    # process depth image
    cur_depth = ros_numpy.numpify(depth)

    # process point cloud
    pc_data = ros_numpy.point_cloud2.pointcloud2_to_array(pc)
    cur_pc = ros_numpy.point_cloud2.get_xyz_points(pc_data)
    cur_pc = cur_pc.reshape((720, 1280, 3))

    # test
    # print(np.shape(cur_image), np.shape(cur_depth), np.shape(cur_pc))

    # color thresholding
    lower = (0, 0, 135)
    upper = (125, 125, 255)
    mask = cv2.inRange(cur_image, lower, upper)
    mask = cv2.cvtColor(mask.copy(), cv2.COLOR_GRAY2BGR)
    mask = (mask/255).astype(int)

    filtered_pc = cur_pc*mask
    filtered_pc = filtered_pc[((filtered_pc[:, :, 0] != 0) | (filtered_pc[:, :, 1] != 0) | (filtered_pc[:, :, 2] != 0))]
    filtered_pc = filtered_pc[filtered_pc[:, 2] < 0.605]
    filtered_pc = filtered_pc[filtered_pc[:, 2] > 0.5]

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
    print(np.shape(filtered_pc))

    # add color
    pc_rgba = struct.unpack('I', struct.pack('BBBB', 255, 0, 0, 255))[0]
    pc_rgba_arr = np.full((len(filtered_pc), 1), pc_rgba)
    filtered_pc_colored = np.hstack((filtered_pc, pc_rgba_arr)).astype('O')
    filtered_pc_colored[:, 3] = filtered_pc_colored[:, 3].astype(int)

    print(np.shape(filtered_pc_colored), filtered_pc_colored[0, 3])

    # filtered_pc = filtered_pc.reshape((len(filtered_pc)*len(filtered_pc[0]), 3))
    header.stamp = rospy.Time.now()
    converted_points = pcl2.create_cloud(header, fields, filtered_pc_colored)
    pc_pub.publish(converted_points)

    # register nodes
    if not initialized:
        init_nodes, _ = register(filtered_pc, 35, mu=0, max_iter=50)
        init_nodes = np.array(sort_pts(init_nodes.tolist()))
        initialized = True
        # header.stamp = rospy.Time.now()
        # converted_init_nodes = pcl2.create_cloud(header, fields, init_nodes)
        # init_nodes_pub.publish(converted_init_nodes)

    # cpd
    if initialized:
        # nodes = cpd(X=filtered_pc, Y_0 = init_nodes, beta=1, alpha=1, k=4, gamma=2, mu=0.05, max_iter=30, tol=0.00001)
        nodes = cpd(X=filtered_pc, Y_0 = init_nodes, beta=2, alpha=1, k=6, gamma=3, mu=0.05, max_iter=30, tol=0.00001)
        init_nodes = nodes
        print("finished reg")

        # add color
        nodes_rgba = struct.unpack('I', struct.pack('BBBB', 0, 0, 0, 255))[0]
        nodes_rgba_arr = np.full((len(nodes), 1), nodes_rgba)
        nodes_colored = np.hstack((nodes, nodes_rgba_arr)).astype('O')
        nodes_colored[:, 3] = nodes_colored[:, 3].astype(int)
        header.stamp = rospy.Time.now()
        converted_nodes = pcl2.create_cloud(header, fields, nodes_colored)
        nodes_pub.publish(converted_nodes)

        # project and pub image
        nodes_h = np.hstack((nodes, np.ones((len(nodes), 1))))
        # proj_matrix: 3*4; nodes_h.T: 4*M; result: 3*M
        image_coords = np.matmul(proj_matrix, nodes_h.T).T
        us = (image_coords[:, 0] / image_coords[:, 2]).astype(int)
        vs = (image_coords[:, 1] / image_coords[:, 2]).astype(int)

        tracking_img = cur_image.copy()
        for i in range (len(image_coords)):
            # draw circle
            uv = (us[i], vs[i])
            cv2.circle(tracking_img, uv, 5, (0, 255, 0), -1)

            # draw line
            if i != len(image_coords)-1:
                cv2.line(tracking_img, uv, (us[i+1], vs[i+1]), (0, 255, 0), 2)
        
        tracking_img_msg = ros_numpy.msgify(Image, tracking_img, 'rgb8')
        tracking_img_pub.publish(tracking_img_msg)



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
    init_nodes_pub = rospy.Publisher ('/init_nodes', PointCloud2, queue_size=10)
    nodes_pub = rospy.Publisher ('/nodes', PointCloud2, queue_size=10)
    tracking_img_pub = rospy.Publisher ('/tracking_img', Image, queue_size=10)

    ts = message_filters.TimeSynchronizer([rgb_sub, depth_sub, pc_sub], 10)
    ts.registerCallback(callback)

    rospy.spin()