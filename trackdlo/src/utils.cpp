#include "../include/trackdlo.h"
#include "../include/utils.h"

using Eigen::MatrixXd;
using Eigen::RowVectorXd;
using cv::Mat;

void signal_callback_handler(int signum) {
   // Terminate program
   exit(signum);
}

double pt2pt_dis_sq (MatrixXd pt1, MatrixXd pt2) {
    return (pt1 - pt2).rowwise().squaredNorm().sum();
}

double pt2pt_dis (MatrixXd pt1, MatrixXd pt2) {
    return (pt1 - pt2).rowwise().norm().sum();
}

void reg (MatrixXd pts, MatrixXd& Y, double& sigma2, int M, double mu, int max_iter) {
    // initial guess
    MatrixXd X = pts.replicate(1, 1);
    Y = MatrixXd::Zero(M, 3);
    for (int i = 0; i < M; i ++) {
        Y(i, 1) = 0.1 / static_cast<double>(M) * static_cast<double>(i);
        Y(i, 0) = 0;
        Y(i, 2) = 0;
    }
    
    int N = X.rows();
    int D = 3;

    // diff_xy should be a (M * N) matrix
    MatrixXd diff_xy = MatrixXd::Zero(M, N);
    for (int i = 0; i < M; i ++) {
        for (int j = 0; j < N; j ++) {
            diff_xy(i, j) = (Y.row(i) - X.row(j)).squaredNorm();
        }
    }

    // initialize sigma2
    sigma2 = diff_xy.sum() / static_cast<double>(D * M * N);

    for (int it = 0; it < max_iter; it ++) {
        // update diff_xy
        for (int i = 0; i < M; i ++) {
            for (int j = 0; j < N; j ++) {
                diff_xy(i, j) = (Y.row(i) - X.row(j)).squaredNorm();
            }
        }

        MatrixXd P = (-0.5 * diff_xy / sigma2).array().exp();
        MatrixXd P_stored = P.replicate(1, 1);
        double c = pow((2 * M_PI * sigma2), static_cast<double>(D)/2) * mu / (1 - mu) * static_cast<double>(M)/N;
        P = P.array().rowwise() / (P.colwise().sum().array() + c);

        MatrixXd Pt1 = P.colwise().sum(); 
        MatrixXd P1 = P.rowwise().sum();
        double Np = P1.sum();
        MatrixXd PX = P * X;

        MatrixXd P1_expanded = MatrixXd::Zero(M, D);
        P1_expanded.col(0) = P1;
        P1_expanded.col(1) = P1;
        P1_expanded.col(2) = P1;

        Y = PX.cwiseQuotient(P1_expanded);

        double numerator = 0;
        double denominator = 0;

        for (int m = 0; m < M; m ++) {
            for (int n = 0; n < N; n ++) {
                numerator += P(m, n)*diff_xy(m, n);
                denominator += P(m, n)*D;
            }
        }

        sigma2 = numerator / denominator;
    }
}

// link to original code: https://stackoverflow.com/a/46303314
void remove_row(MatrixXd& matrix, unsigned int rowToRemove) {
    unsigned int numRows = matrix.rows()-1;
    unsigned int numCols = matrix.cols();

    if( rowToRemove < numRows )
        matrix.block(rowToRemove,0,numRows-rowToRemove,numCols) = matrix.bottomRows(numRows-rowToRemove);

    matrix.conservativeResize(numRows,numCols);
}

MatrixXd sort_pts (MatrixXd Y_0) {
    int N = Y_0.rows();
    MatrixXd Y_0_sorted = MatrixXd::Zero(N, 3);
    std::vector<MatrixXd> Y_0_sorted_vec = {};
    std::vector<bool> selected_node(N, false);
    selected_node[0] = true;
    int last_visited_b = 0;

    MatrixXd G = MatrixXd::Zero(N, N);
    for (int i = 0; i < N; i ++) {
        for (int j = 0; j < N; j ++) {
            G(i, j) = (Y_0.row(i) - Y_0.row(j)).squaredNorm();
        }
    }

    int reverse = 0;
    int counter = 0;
    int reverse_on = 0;
    int insertion_counter = 0;

    while (counter < N-1) {
        double minimum = INFINITY;
        int a = 0;
        int b = 0;

        for (int m = 0; m < N; m ++) {
            if (selected_node[m] == true) {
                for (int n = 0; n < N; n ++) {
                    if ((!selected_node[n]) && (G(m, n) != 0.0)) {
                        if (minimum > G(m, n)) {
                            minimum = G(m, n);
                            a = m;
                            b = n;
                        }
                    }
                }
            }
        }

        if (counter == 0) {
            Y_0_sorted_vec.push_back(Y_0.row(a));
            Y_0_sorted_vec.push_back(Y_0.row(b));
        }
        else {
            if (last_visited_b != a) {
                reverse += 1;
                reverse_on = a;
                insertion_counter = 1;
            }
            
            if (reverse % 2 == 1) {
                auto it = find(Y_0_sorted_vec.begin(), Y_0_sorted_vec.end(), Y_0.row(a));
                Y_0_sorted_vec.insert(it, Y_0.row(b));
            }
            else if (reverse != 0) {
                auto it = find(Y_0_sorted_vec.begin(), Y_0_sorted_vec.end(), Y_0.row(reverse_on));
                Y_0_sorted_vec.insert(it + insertion_counter, Y_0.row(b));
                insertion_counter += 1;
            }
            else {
                Y_0_sorted_vec.push_back(Y_0.row(b));
            }
        }

        last_visited_b = b;
        selected_node[b] = true;
        counter += 1;
    }

    // copy to Y_0_sorted
    for (int i = 0; i < N; i ++) {
        Y_0_sorted.row(i) = Y_0_sorted_vec[i];
    }

    return Y_0_sorted;
}

bool isBetween (MatrixXd x, MatrixXd a, MatrixXd b) {
    bool in_bound = true;

    for (int i = 0; i < 3; i ++) {
        if (!(a(0, i)-0.0001 <= x(0, i) && x(0, i) <= b(0, i)+0.0001) && 
            !(b(0, i)-0.0001 <= x(0, i) && x(0, i) <= a(0, i)+0.0001)) {
            in_bound = false;
        }
    }
    
    return in_bound;
}

std::vector<MatrixXd> line_sphere_intersection (MatrixXd point_A, MatrixXd point_B, MatrixXd sphere_center, double radius) {
    std::vector<MatrixXd> intersections = {};
    
    double a = pt2pt_dis_sq(point_A, point_B);
    double b = 2 * ((point_B(0, 0) - point_A(0, 0))*(point_A(0, 0) - sphere_center(0, 0)) + 
                    (point_B(0, 1) - point_A(0, 1))*(point_A(0, 1) - sphere_center(0, 1)) + 
                    (point_B(0, 2) - point_A(0, 2))*(point_A(0, 2) - sphere_center(0, 2)));
    double c = pt2pt_dis_sq(point_A, sphere_center) - pow(radius, 2);
    
    double delta = pow(b, 2) - 4*a*c;

    double d1 = (-b + sqrt(delta)) / (2*a);
    double d2 = (-b - sqrt(delta)) / (2*a);

    if (delta < 0) {
        // no solution
        return {};
    }
    else if (delta > 0) {
        // two solutions
        // the first one
        double x1 = point_A(0, 0) + d1*(point_B(0, 0) - point_A(0, 0));
        double y1 = point_A(0, 1) + d1*(point_B(0, 1) - point_A(0, 1));
        double z1 = point_A(0, 2) + d1*(point_B(0, 2) - point_A(0, 2));
        MatrixXd pt1(1, 3);
        pt1 << x1, y1, z1;

        // the second one
        double x2 = point_A(0, 0) + d2*(point_B(0, 0) - point_A(0, 0));
        double y2 = point_A(0, 1) + d2*(point_B(0, 1) - point_A(0, 1));
        double z2 = point_A(0, 2) + d2*(point_B(0, 2) - point_A(0, 2));
        MatrixXd pt2(1, 3);
        pt2 << x2, y2, z2;

        if (isBetween(pt1, point_A, point_B)) {
            intersections.push_back(pt1);
        }
        if (isBetween(pt2, point_A, point_B)) {
            intersections.push_back(pt2);
        }
    }
    else {
        // one solution
        d1 = -b / (2*a);
        double x1 = point_A(0, 0) + d1*(point_B(0, 0) - point_A(0, 0));
        double y1 = point_A(0, 1) + d1*(point_B(0, 1) - point_A(0, 1));
        double z1 = point_A(0, 2) + d1*(point_B(0, 2) - point_A(0, 2));
        MatrixXd pt1(1, 3);
        pt1 << x1, y1, z1;

        if (isBetween(pt1, point_A, point_B)) {
            intersections.push_back(pt1);
        }
    }
    
    return intersections;
}

std::tuple<MatrixXd, MatrixXd, double> shortest_dist_between_lines (MatrixXd a0, MatrixXd a1, MatrixXd b0, MatrixXd b1, bool clamp) {
    MatrixXd A = a1 - a0;
    MatrixXd B = b1 - b0;
    MatrixXd A_normalized = A / A.norm();
    MatrixXd B_normalized = B / B.norm();

    MatrixXd cross = cross_product(A_normalized, B_normalized);
    double denom = cross.squaredNorm();

    // If lines are parallel (denom=0) test if lines overlap.
    // If they don't overlap then there is a closest point solution.
    // If they do overlap, there are infinite closest positions, but there is a closest distance
    if (denom == 0) {
        double d0 = dot_product(A_normalized, b0-a0);

        // Overlap only possible with clamping
        if (clamp) {
            double d1 = dot_product(A_normalized, b1-a0);

            // is segment B before A?
            if (d0 <= 0 && d1 <= 0) {
                if (abs(d0) < abs(d1)) {
                    return {a0, b0, (a0-b0).norm()};
                }
                else {
                    return {a0, b1, (a0-b1).norm()};
                }
            }

            // is segment B after A?
            else if (d0 >= A.norm() && d1 >= A.norm()) {
                if (abs(d0) < abs(d1)) {
                    return {a1, b0, (a1-b0).norm()};
                }
                else {
                    return {a1, b1, (a1-b1).norm()};
                }
            }
        }

        // Segments overlap, return distance between parallel segments
        return {MatrixXd::Zero(1, 3), MatrixXd::Zero(1, 3), (d0*A_normalized+a0-b0).norm()};
    }

    // Lines criss-cross: Calculate the projected closest points
    MatrixXd t = b0 - a0;
    MatrixXd tempA = MatrixXd::Zero(3, 3);
    tempA.block(0, 0, 1, 3) = t;
    tempA.block(1, 0, 1, 3) = B_normalized;
    tempA.block(2, 0, 1, 3) = cross;

    MatrixXd tempB = MatrixXd::Zero(3, 3);
    tempB.block(0, 0, 1, 3) = t;
    tempB.block(1, 0, 1, 3) = A_normalized;
    tempB.block(2, 0, 1, 3) = cross;

    double t0 = tempA.determinant() / denom;
    double t1 = tempB.determinant() / denom;

    MatrixXd pA = a0 + (A_normalized * t0);  // projected closest point on segment A
    MatrixXd pB = b0 + (B_normalized * t1);  // projected closest point on segment B

    // clamp
    if (clamp) {
        if (t0 < 0) {
            pA = a0.replicate(1, 1);
        }
        else if (t0 > A.norm()) {
            pA = a1.replicate(1, 1);
        }

        if (t1 < 0) {
            pB = b0.replicate(1, 1);
        }
        else if (t1 > B.norm()) {
            pB = b1.replicate(1, 1);
        }

        // clamp projection A
        if (t0 < 0 || t0 > A.norm()) {
            double dot = dot_product(B_normalized, pA-b0);
            if (dot < 0) {
                dot = 0;
            }
            else if (dot > B.norm()) {
                dot = B.norm();
            }
            pB = b0 + (B_normalized * dot);
        }

        // clamp projection B
        if (t1 < 0 || t1 > B.norm()) {
            double dot = dot_product(A_normalized, pB-a0);
            if (dot < 0) {
                dot = 0;
            }
            else if (dot > A.norm()) {
                dot = A.norm();
            }
            pA = a0 + (A_normalized * dot);
        }
    }

    return {pA, pB, (pA-pB).norm()};
}

static GRBEnv& getGRBEnv () {
    static GRBEnv env;
    return env;
}

MatrixXd post_processing (MatrixXd Y_0, MatrixXd Y, double check_distance, double dlo_diameter, int nodes_per_dlo, bool clamp) {
    MatrixXd Y_processed = MatrixXd::Zero(Y.rows(), Y.cols());
    int num_of_dlos = Y.rows() / nodes_per_dlo;

    GRBVar* vars = nullptr;
    GRBEnv& env = getGRBEnv();
    env.set(GRB_IntParam_OutputFlag, 0);
    GRBModel model(env);
    // model.set("ScaleFlag", "0");
    // model.set("FeasibilityTol", "0.01");

    // add vars to the model
    const ssize_t num_of_vars = 3 * Y.rows();
    const std::vector<double> lower_bound(num_of_vars, -GRB_INFINITY);
    const std::vector<double> upper_bound(num_of_vars, GRB_INFINITY);
    vars = model.addVars(lower_bound.data(), upper_bound.data(), nullptr, nullptr, nullptr, (int) num_of_vars);

    // add constraints to the model
    for (int i = 0; i < Y.rows()-1; i ++) {
        for (int j = i; j < Y.rows()-1; j ++) {
            // edge 1: y_i, y_{i+1}
            // edge 2: y_j, y_{j+1}
            if (abs(i - j) <= 1) {
                continue;
            }

            // for multiple dlos
            if (num_of_dlos > 1) {
                if ((i+1) % nodes_per_dlo == 0 || (j+1) % nodes_per_dlo == 0) {
                    continue;
                }
            }

            auto[temp1, temp2, cur_shortest_dist] = shortest_dist_between_lines(Y.row(i), Y.row(i+1), Y.row(j), Y.row(j+1), true);
            if (cur_shortest_dist >= check_distance) {
                continue;
            }

            auto[pA, pB, dist] = shortest_dist_between_lines(Y_0.row(i), Y_0.row(i+1), Y_0.row(j), Y_0.row(j+1), clamp);

            std::cout << "Adding self-intersection constraint between E(" << i << ", " << i+1 << ") and E(" << j << ", " << j+1 << ")" << std::endl;

            // pA is the point on edge y_i, y_{i+1}
            // pB is the point on edge y_j, y_{j+1}
            // the below definition should be consistent with CDCPD2's Eq 18-21
            double r_i = ((pA - Y.row(i+1)).array() / (Y.row(i) - Y.row(i+1)).array())(0, 0);
            double r_j = ((pB - Y.row(j+1)).array() / (Y.row(j) - Y.row(j+1)).array())(0, 0);

            std::cout << "r_i, r_j = " << r_i << ", " << r_j << std::endl;

            // === Python ===
            // pA_var = r_i*vars[i] + (1 - r_i)*vars[i+1]
            // pB_var = r_j*vars[j] + (1 - r_j)*vars[j+1]
            // // model.addConstr(operator.ge(np.sum(np.square(pA_var - pB_var)), dlo_diameter**2))
            // model.addConstr(operator.ge(((pA_var[0] - pB_var[0])*(pA[0] - pB[0]) +
            //                              (pA_var[1] - pB_var[1])*(pA[1] - pB[1]) +
            //                              (pA_var[2] - pB_var[2])*(pA[2] - pB[2])) / np.linalg.norm(pA - pB), dlo_diameter))

            // vars can be seen as a flattened array of size len(Y)*3
            model.addConstr((((r_i*vars[3*i] + (1 - r_i)*vars[3*(i+1)]) - (r_j*vars[3*j] + (1 - r_j)*vars[3*(j+1)])) * (pA(0, 0) - pB(0, 0)) +
                             ((r_i*vars[3*i+1] + (1 - r_i)*vars[3*(i+1)+1]) - (r_j*vars[3*j+1] + (1 - r_j)*vars[3*(j+1)+1])) * (pA(0, 1) - pB(0, 1)) +
                             ((r_i*vars[3*i+2] + (1 - r_i)*vars[3*(i+1)+2]) - (r_j*vars[3*j+2] + (1 - r_j)*vars[3*(j+1)+2])) * (pA(0, 2) - pB(0, 2))) / (pA - pB).norm()
                            >= dlo_diameter);
        }
    }

    // objective function (as close to Y as possible)
    GRBQuadExpr objective_fn(0);
    for (ssize_t i = 0; i < Y.rows(); i ++) {
        const auto expr0 = vars[3*i] - Y(i, 0);
        const auto expr1 = vars[3*i+1] - Y(i, 1);
        const auto expr2 = vars[3*i+2] - Y(i, 2);
        objective_fn += expr0 * expr0;
        objective_fn += expr1 * expr1;
        objective_fn += expr2 * expr2;
    }
    model.setObjective(objective_fn, GRB_MINIMIZE);

    model.update();
    model.optimize();
    if (model.get(GRB_IntAttr_Status) == GRB_OPTIMAL || model.get(GRB_IntAttr_Status) == GRB_SUBOPTIMAL) {
        for (ssize_t i = 0; i < Y.rows(); i ++) {
            Y_processed(i, 0) = vars[3*i].get(GRB_DoubleAttr_X);
            Y_processed(i, 1) = vars[3*i+1].get(GRB_DoubleAttr_X);
            Y_processed(i, 2) = vars[3*i+2].get(GRB_DoubleAttr_X);
        }
    }
    else {
        std::cout << "Status: " << model.get(GRB_IntAttr_Status) << std::endl;
        exit(-1);
    }

    return Y_processed;
}

// node color and object color are in rgba format and range from 0-1
visualization_msgs::MarkerArray MatrixXd2MarkerArray (MatrixXd Y,
                                                      std::string marker_frame, 
                                                      std::string marker_ns, 
                                                      std::vector<float> node_color, 
                                                      std::vector<float> line_color, 
                                                      double node_scale,
                                                      double line_scale,
                                                      std::vector<int> visible_nodes, 
                                                      std::vector<float> occluded_node_color,
                                                      std::vector<float> occluded_line_color) {    // publish the results as a marker array
    
    visualization_msgs::MarkerArray results = visualization_msgs::MarkerArray();
    
    bool last_node_visible = true;
    for (int i = 0; i < Y.rows(); i ++) {
        visualization_msgs::Marker cur_node_result = visualization_msgs::Marker();
    
        // add header
        cur_node_result.header.frame_id = marker_frame;
        // cur_node_result.header.stamp = ros::Time::now();
        cur_node_result.type = visualization_msgs::Marker::SPHERE;
        cur_node_result.action = visualization_msgs::Marker::ADD;
        cur_node_result.ns = marker_ns + "_node_" + std::to_string(i);
        cur_node_result.id = i;

        // add position
        cur_node_result.pose.position.x = Y(i, 0);
        cur_node_result.pose.position.y = Y(i, 1);
        cur_node_result.pose.position.z = Y(i, 2);

        // add orientation
        cur_node_result.pose.orientation.w = 1.0;
        cur_node_result.pose.orientation.x = 0.0;
        cur_node_result.pose.orientation.y = 0.0;
        cur_node_result.pose.orientation.z = 0.0;

        // set scale
        cur_node_result.scale.x = node_scale;
        cur_node_result.scale.y = node_scale;
        cur_node_result.scale.z = node_scale;

        // set color
        bool cur_node_visible;
        if (visible_nodes.size() != 0 && std::find(visible_nodes.begin(), visible_nodes.end(), i) == visible_nodes.end()) {
            cur_node_result.color.r = occluded_node_color[0];
            cur_node_result.color.g = occluded_node_color[1];
            cur_node_result.color.b = occluded_node_color[2];
            cur_node_result.color.a = occluded_node_color[3];
            cur_node_visible = false;
        }
        else {
            cur_node_result.color.r = node_color[0];
            cur_node_result.color.g = node_color[1];
            cur_node_result.color.b = node_color[2];
            cur_node_result.color.a = node_color[3];
            cur_node_visible = true;
        }

        results.markers.push_back(cur_node_result);

        // don't add line if at the first node
        if (i == 0) {
            continue;
        }

        visualization_msgs::Marker cur_line_result = visualization_msgs::Marker();

        // add header
        cur_line_result.header.frame_id = marker_frame;
        cur_line_result.type = visualization_msgs::Marker::CYLINDER;
        cur_line_result.action = visualization_msgs::Marker::ADD;
        cur_line_result.ns = marker_ns + "_line_" + std::to_string(i);
        cur_line_result.id = i;

        // add position
        cur_line_result.pose.position.x = (Y(i, 0) + Y(i-1, 0)) / 2.0;
        cur_line_result.pose.position.y = (Y(i, 1) + Y(i-1, 1)) / 2.0;
        cur_line_result.pose.position.z = (Y(i, 2) + Y(i-1, 2)) / 2.0;

        // add orientation
        Eigen::Quaternionf q;
        Eigen::Vector3f vec1(0.0, 0.0, 1.0);
        Eigen::Vector3f vec2(Y(i, 0) - Y(i-1, 0), Y(i, 1) - Y(i-1, 1), Y(i, 2) - Y(i-1, 2));
        q.setFromTwoVectors(vec1, vec2);

        cur_line_result.pose.orientation.w = q.w();
        cur_line_result.pose.orientation.x = q.x();
        cur_line_result.pose.orientation.y = q.y();
        cur_line_result.pose.orientation.z = q.z();

        // set scale
        cur_line_result.scale.x = line_scale;
        cur_line_result.scale.y = line_scale;
        cur_line_result.scale.z = pt2pt_dis(Y.row(i), Y.row(i-1));

        // set color
        if (last_node_visible && cur_node_visible) {
            cur_line_result.color.r = line_color[0];
            cur_line_result.color.g = line_color[1];
            cur_line_result.color.b = line_color[2];
            cur_line_result.color.a = line_color[3];
        }
        else {
            cur_line_result.color.r = occluded_line_color[0];
            cur_line_result.color.g = occluded_line_color[1];
            cur_line_result.color.b = occluded_line_color[2];
            cur_line_result.color.a = occluded_line_color[3];
        }

        results.markers.push_back(cur_line_result);
    }

    return results;
}

// overload function
visualization_msgs::MarkerArray MatrixXd2MarkerArray (std::vector<MatrixXd> Y,
                                                      std::string marker_frame, 
                                                      std::string marker_ns, 
                                                      std::vector<float> node_color, 
                                                      std::vector<float> line_color, 
                                                      double node_scale,
                                                      double line_scale,
                                                      std::vector<int> visible_nodes, 
                                                      std::vector<float> occluded_node_color,
                                                      std::vector<float> occluded_line_color) {
    // publish the results as a marker array
    visualization_msgs::MarkerArray results = visualization_msgs::MarkerArray();

    bool last_node_visible = true;
    for (int i = 0; i < Y.size(); i ++) {
        visualization_msgs::Marker cur_node_result = visualization_msgs::Marker();

        int dim = Y[0].cols();
    
        // add header
        cur_node_result.header.frame_id = marker_frame;
        // cur_node_result.header.stamp = ros::Time::now();
        cur_node_result.type = visualization_msgs::Marker::SPHERE;
        cur_node_result.action = visualization_msgs::Marker::ADD;
        cur_node_result.ns = marker_ns + "_node_" + std::to_string(i);
        cur_node_result.id = i;

        // add position
        cur_node_result.pose.position.x = Y[i](0, dim-3);
        cur_node_result.pose.position.y = Y[i](0, dim-2);
        cur_node_result.pose.position.z = Y[i](0, dim-1);

        // add orientation
        cur_node_result.pose.orientation.w = 1.0;
        cur_node_result.pose.orientation.x = 0.0;
        cur_node_result.pose.orientation.y = 0.0;
        cur_node_result.pose.orientation.z = 0.0;

        // set scale
        cur_node_result.scale.x = 0.01;
        cur_node_result.scale.y = 0.01;
        cur_node_result.scale.z = 0.01;

        // set color
        bool cur_node_visible;
        if (visible_nodes.size() != 0 && std::find(visible_nodes.begin(), visible_nodes.end(), i) == visible_nodes.end()) {
            cur_node_result.color.r = occluded_node_color[0];
            cur_node_result.color.g = occluded_node_color[1];
            cur_node_result.color.b = occluded_node_color[2];
            cur_node_result.color.a = occluded_node_color[3];
            cur_node_visible = false;
        }
        else {
            cur_node_result.color.r = node_color[0];
            cur_node_result.color.g = node_color[1];
            cur_node_result.color.b = node_color[2];
            cur_node_result.color.a = node_color[3];
            cur_node_visible = true;
        }

        results.markers.push_back(cur_node_result);

        // don't add line if at the first node
        if (i == 0) {
            continue;
        }

        visualization_msgs::Marker cur_line_result = visualization_msgs::Marker();

        // add header
        cur_line_result.header.frame_id = marker_frame;
        cur_line_result.type = visualization_msgs::Marker::CYLINDER;
        cur_line_result.action = visualization_msgs::Marker::ADD;
        cur_line_result.ns = marker_ns + "_line_" + std::to_string(i);
        cur_line_result.id = i;

        // add position
        cur_line_result.pose.position.x = (Y[i](0, dim-3) + Y[i-1](0, dim-3)) / 2.0;
        cur_line_result.pose.position.y = (Y[i](0, dim-2) + Y[i-1](0, dim-2)) / 2.0;
        cur_line_result.pose.position.z = (Y[i](0, dim-1) + Y[i-1](0, dim-1)) / 2.0;

        // add orientation
        Eigen::Quaternionf q;
        Eigen::Vector3f vec1(0.0, 0.0, 1.0);
        Eigen::Vector3f vec2(Y[i](0, dim-3) - Y[i-1](0, dim-3), Y[i](0, dim-2) - Y[i-1](0, dim-2), Y[i](0, dim-1) - Y[i-1](0, dim-1));
        q.setFromTwoVectors(vec1, vec2);

        cur_line_result.pose.orientation.w = q.w();
        cur_line_result.pose.orientation.x = q.x();
        cur_line_result.pose.orientation.y = q.y();
        cur_line_result.pose.orientation.z = q.z();

        // set scale
        cur_line_result.scale.x = 0.005;
        cur_line_result.scale.y = 0.005;
        cur_line_result.scale.z = sqrt(pow(Y[i](0, dim-3) - Y[i-1](0, dim-3), 2) + pow(Y[i](0, dim-2) - Y[i-1](0, dim-2), 2) + pow(Y[i](0, dim-1) - Y[i-1](0, dim-1), 2));

        // set color
        if (last_node_visible && cur_node_visible) {
            cur_line_result.color.r = line_color[0];
            cur_line_result.color.g = line_color[1];
            cur_line_result.color.b = line_color[2];
            cur_line_result.color.a = line_color[3];
        }
        else {
            cur_line_result.color.r = occluded_line_color[0];
            cur_line_result.color.g = occluded_line_color[1];
            cur_line_result.color.b = occluded_line_color[2];
            cur_line_result.color.a = occluded_line_color[3];
        }

        results.markers.push_back(cur_line_result);
    }

    return results;
}

MatrixXd cross_product (MatrixXd vec1, MatrixXd vec2) {
    MatrixXd ret = MatrixXd::Zero(1, 3);
    
    ret(0, 0) = vec1(0, 1)*vec2(0, 2) - vec1(0, 2)*vec2(0, 1);
    ret(0, 1) = -(vec1(0, 0)*vec2(0, 2) - vec1(0, 2)*vec2(0, 0));
    ret(0, 2) = vec1(0, 0)*vec2(0, 1) - vec1(0, 1)*vec2(0, 0);

    return ret;
}

double dot_product (MatrixXd vec1, MatrixXd vec2) {
    return vec1(0, 0)*vec2(0, 0) + vec1(0, 1)*vec2(0, 1) + vec1(0, 2)*vec2(0, 2);
}