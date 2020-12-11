from time import time
import numpy as np
from scipy.optimize import minimize, LinearConstraint, NonlinearConstraint
import random

from kdtree import KDTree
from franka_robot import FrankaRobot


class SimpleTree:

    def __init__(self, dim):
        self._parents_map = {}
        self._kd = KDTree(dim)

    def insert_new_node(self, point, parent=None):
        node_id = self._kd.insert(point)
        self._parents_map[node_id] = parent

        return node_id

    def get_parent(self, child_id):
        return self._parents_map[child_id]

    def get_point(self, node_id):
        return self._kd.get_node(node_id).point

    def get_nearest_node(self, point):
        return self._kd.find_nearest_point(point)

    def construct_path_to_root(self, leaf_node_id):
        path = []
        node_id = leaf_node_id
        while node_id is not None:
            path.append(self.get_point(node_id))
            node_id = self.get_parent(node_id)

        return path
    def get_num_nodes(self):
        return len(self._parents_map)


class RRTConnect:

    def __init__(self, fr, is_in_collision):
        self._fr = fr
        self._is_in_collision = is_in_collision

        self._q_step_size = 0.04
        self._connect_dist = 0.1
        self._max_n_nodes = int(1e5)
        self._smoothed_nodes = 60
        self._constraint_th = 1e-3  # Default: 1e-3
        self._project_step_size = 1e-1  # Default:1e-1

    def sample_valid_joints(self):
        q = np.random.random(self._fr.num_dof) * (self._fr.joint_limits_high - self._fr.joint_limits_low) + self._fr.joint_limits_low
        return q

    def project_to_constraint(self, q, constraint):
        '''
        TODO: Implement projecting a configuration to satisfy a constraint function using gradient descent.

        Please use the following parameters in your code:
            self._project_step_size - learning rate for gradient descent
            self._constraint_th - a threshold lower than which the constraint is considered to be satisfied

        Input:
            q - the point to be projected
            constraint - a function of q that returns (constraint_value, constraint_gradient)
                         constraint_value is a scalar - it is 0 when the constraint is satisfied
                         constraint_gradient is a vector of length 6 - it is the gradient of the
                                constraint value w.r.t. the end-effector pose (x, y, z, r, p, y)

        Output:
            q_proj - the projected point

        You can obtain the Jacobian by calling self._fr.jacobian(q)
        '''
        q_proj = q.copy()
        err, grad = constraint(q)
        while err > self._constraint_th:
            # print('The error is: ', err)
            J = self._fr.jacobian(q_proj)
            q_proj -= self._project_step_size * J.T.dot(grad)
            # q_proj -= self._project_step_size * J.T.dot(np.linalg.inv(J.dot(J.T))).dot(grad)
            err, grad = constraint(q_proj)
        return q_proj

    def _is_seg_valid(self, q0, q1):
        qs = np.linspace(q0, q1, int(np.linalg.norm(q1 - q0) / self._q_step_size))
        for q in qs:
            if self._is_in_collision(q):
                return False
        return True

    def constrained_extend(self, tree, q_near, q_target, q_near_id, constraint=None):
        '''
        TODO: Implement extend for RRT Connect
        - Only perform self.project_to_constraint if constraint is not None
        - Use self._is_seg_valid, self._q_step_size, self._connect_dist
        '''
        qs = qs_old = q_near
        qs_id = qs_old_id = q_near_id
        while True:
            if (q_target == qs).all():
                return qs, qs_id
            if np.linalg.norm(q_target - qs) > np.linalg.norm(qs_old - q_target):
                return qs_old, qs_old_id
            qs_old = qs
            qs_old_id = qs_id

            qs = qs + min(self._q_step_size, np.linalg.norm(q_target - qs)) * (q_target - qs) / np.linalg.norm(q_target - qs)
            if constraint:
                qs = self.project_to_constraint(qs, constraint)

            if not self._is_in_collision(qs) and self._is_seg_valid(qs_old, qs):
                qs_id = tree.insert_new_node(qs, qs_old_id)
            else:
                return qs_old, qs_old_id

    def getDistance(self, p):
        dist = 0
        prev = p[0]
        for q in p[1:]:
            dist += np.linalg.norm(q - prev)
            prev = q
        return dist

    def smoothPath(self, path, constraint):
        for num_smoothed in range(self._smoothed_nodes):
            tree = SimpleTree(len(path[0]))
            i = random.randint(0, len(path) - 2)
            j = random.randint(i + 1, len(path) - 1)
            q_reach, q_reach_id = self.constrained_extend(tree, path[i], path[j], None, constraint)
            if not (q_reach == path[j]).all():
                continue
            # print(i, j, q_reach_id)
            temp_path = tree.construct_path_to_root(q_reach_id)
            # print(temp_path[::-1])
            # print(path[i:j+1])
            if self.getDistance(temp_path) < self.getDistance(path[i:j+1]):
                path = path[:i+1] + temp_path[::-1] + path[j+1:]
        return path


    def plan(self, q_start, q_target, constraint=None):
        tree_0 = SimpleTree(len(q_start))
        tree_0.insert_new_node(q_start)

        tree_1 = SimpleTree(len(q_target))
        tree_1.insert_new_node(q_target)

        q_start_is_tree_0 = True

        s = time()
        for n_nodes_sampled in range(self._max_n_nodes):
            if n_nodes_sampled > 0 and n_nodes_sampled % 100 == 0:
                print('RRT: Sampled {} nodes'.format(n_nodes_sampled))
            q_rand = self.sample_valid_joints()
            node_id_near_0 = tree_0.get_nearest_node(q_rand)[0]
            q_near_0 = tree_0.get_point(node_id_near_0)
            qa_reach, qa_reach_id = self.constrained_extend(tree_0, q_near_0, q_rand, node_id_near_0, constraint)

            node_id_near_1 = tree_1.get_nearest_node(qa_reach)[0]
            q_near_1 = tree_1.get_point(node_id_near_1)
            qb_reach, qb_reach_id = self.constrained_extend(tree_1, q_near_1, qa_reach, node_id_near_1, constraint)

            if (qa_reach == qb_reach).all():
                reached_target = True
                print(q_start_is_tree_0)
                break

            q_start_is_tree_0 = not q_start_is_tree_0
            tree_0, tree_1 = tree_1, tree_0

        print('RRT: Sampled {} nodes in {:.2f}s'.format(n_nodes_sampled, time() - s))

        # if not q_start_is_tree_0:
        #     tree_0, tree_1 = tree_1, tree_0
        print('RRTC: {} nodes extended in {:.2f}s'.format(tree_0.get_num_nodes() + tree_1.get_num_nodes(), time() - s))

        if reached_target:
            tree_0_backward_path = tree_0.construct_path_to_root(qa_reach_id)
            tree_1_forward_path = tree_1.construct_path_to_root(qb_reach_id)

            # q0 = tree_0_backward_path[0]
            # q1 = tree_1_forward_path[0]
            # tree_01_connect_path = np.linspace(q0, q1, int(np.linalg.norm(q1 - q0) / self._q_step_size))[1:].tolist()
            if not q_start_is_tree_0:
                path = tree_1_forward_path[::-1] + tree_0_backward_path
            else:
                path = tree_0_backward_path[::-1] + tree_1_forward_path
            print('RRT: Found a path! Path length is {}.'.format(len(path)))
        else:
            path = []
            print('RRT: Was not able to find a path!')
        path = self.smoothPath(path, constraint)
        return np.array(path).tolist()
