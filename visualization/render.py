import os
import shutil
import subprocess
import numpy as np
import quaternion
from matplotlib import pyplot as plt, animation as animation
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from visualization.fk import SMPLForwardKinematics

from common.utils import is_valid_rotmat, aa2rotmat, rotmat2aa, get_closest_rotmat, sparse_to_full
from fk import SMPL_MAJOR_JOINTS, SMPL_NR_JOINTS, SMPL_PARENTS

_prop_cycle = plt.rcParams['axes.prop_cycle']
_colors = _prop_cycle.by_key()['color']


class Visualizer(object):
    """
    Helper class to visualize SMPL joint angle input.
    """
    def __init__(self, fk_engine, video_dir=None, frames_dir=None, rep="rotmat", is_sparse=True, smpl_model=None):
        self.fk_engine = fk_engine
        self.video_dir = video_dir  # if not None saves to mp4
        self.frames_dir = frames_dir  # if not None dumps individual frames
        self.rep = rep
        self.is_sparse = is_sparse
        self.expected_n_input_joints = len(self.fk_engine.major_joints) if is_sparse else self.fk_engine.n_joints
        assert rep in ["rotmat", "quat", "aa"]
        assert self.video_dir or self.frames_dir, "Save path required for either video or frames."
        
        self.smpl_model = smpl_model

    def visualize_dense_smpl(self, joint_angles, fname, dense=True, alpha=0.2):
        """
        Visualize the dense SMPL surface from the given joint angles.
        Args:
            joint_angles: A numpy array of shape (seq_length, n_joints*dof)
        """
        assert isinstance(self.fk_engine, SMPLForwardKinematics)
        if self.rep == "quat":
            raise NotImplementedError()
        elif self.rep == "rotmat":
            rotmats = np.reshape(joint_angles, [joint_angles.shape[0], -1, 3, 3])
            aas = rotmat2aa(rotmats)
            aas = np.reshape(aas, [joint_angles.shape[0], -1])
        else:
            # this is angle-axis, nothing to do
            aas = joint_angles

        aas_full = sparse_to_full(aas, SMPL_MAJOR_JOINTS, SMPL_NR_JOINTS, rep="aa")

        # TODO(kamanuel) make this more efficient and less hacky
        # load the SMPL model
        if self.smpl_model is None:
            try:
                # import sys
                # sys.path.append('../external/smpl_py3')
                from external.smpl_py3.smpl_webuser.serialization import load_model
                self.smpl_model = load_model('../external/smpl_py3/models/basicModel_m_lbs_10_207_0_v1.0.0.pkl')
                smpl_m = self.smpl_model
            except:
                raise Exception("SMPL model not available.")
        else:
            smpl_m = self.smpl_model

        fname = fname.replace('/', '.')
        fname = fname.split('_')[0]  # reduce name otherwise stupid OSes (like all of them) can't handle it
        if self.frames_dir is None:
            save_to = os.path.join(self.video_dir, fname, "tmp_smpl/")  # Delete this temporary directory afterwards.
        else:
            save_to = os.path.join(self.frames_dir, fname, "frames_smpl/")
        
        if not os.path.exists(save_to):
            os.makedirs(save_to)

        for fr in range(aas_full.shape[0]):
            one_pose = aas_full[fr]
            smpl_m.pose[:] = one_pose
            visualize_smpl_mesh(smpl_m.r.copy(), smpl_m.f, smpl_m.J_transformed.r.copy(), show=False,
                                save_to=os.path.join(save_to, 'frame_{:0>4}.png'.format(fr)), dense=dense,
                                alpha=alpha)
        
        if self.video_dir is not None:
            video_path = os.path.join(self.video_dir, fname, fname+"_smpl.mp4")
            frame_path = os.path.join(save_to, 'frame_%04d.png')
            create_mp4_clip(video_path, frame_path)
            
        # Delete frames if they are not required to store.
        if self.frames_dir is None:
            shutil.rmtree(save_to)
            
    def visualize_skeleton(self, joint_angles, fname):
        assert joint_angles.shape[-1] == self.expected_n_input_joints * 9
        n_joints = self.expected_n_input_joints
        
        # calculate positions
        joint_angles = np.reshape(joint_angles, [-1, n_joints, 3, 3])
        if self.is_sparse:
            pos = self.fk_engine.from_sparse(joint_angles, return_sparse=False)  # (N, full_n_joints, 3)
        else:
            pos = self.fk_engine.from_rotmat(joint_angles)
        pos = pos[..., [0, 2, 1]]
    
        fname = fname.replace('/', '.')
        fname = fname.split('_')[0]  # reduce name otherwise stupid OSes (like all of them) can't handle it
    
        out_name, save_to = None, None
        if self.video_dir is not None:
            out_name = os.path.join(self.video_dir, fname, fname + "_skeleton.mp4")
        if self.frames_dir is not None:
            save_to = os.path.join(self.frames_dir, fname, "frames_skeleton/")
    
        visualize_positions(positions=[pos],
                            colors=[_colors[0]],
                            titles=[""],
                            fig_title=fname,
                            parents=self.fk_engine.parents,
                            out_file=out_name,
                            frame_dir=save_to)
    
    def visualize_results(self, seed, prediction, target, title):
        """
        Visualize prediction and ground truth side by side. At the moment only supports sparse pose input in rotation
        matrix or quaternion format.
        Args:
            seed: A np array of shape (seed_seq_length, n_joints*dof)
            prediction: A np array of shape (target_seq_length, n_joints*dof)
            target: A np array of shape (target_seq_length, n_joints*dof)
            title: Title of the plot
        """
        if self.rep == "quat":
            self.visualize_quat(seed, prediction, target, title)
        elif self.rep == "rotmat":
            self.visualize_rotmat(seed, prediction, target, title)
        else:
            self.visualize_aa(seed, prediction, target, title)

    def visualize_quat(self, seed, prediction, target, title):
        assert seed.shape[-1] == prediction.shape[-1] == target.shape[-1] == self.expected_n_input_joints * 4
        assert prediction.shape[0] == target.shape[0]
        dof = 4

        def _to_rotmat(x):
            b = x.shape[0]
            xq = quaternion.from_float_array(np.reshape(x, [b, -1, dof]))
            xr = quaternion.as_rotation_matrix(xq)
            return np.reshape(xr, [b, -1])

        self.visualize_rotmat(_to_rotmat(seed), _to_rotmat(prediction), _to_rotmat(target), title)

    def visualize_aa(self, seed, prediction, target, title):
        assert seed.shape[-1] == prediction.shape[-1] == target.shape[-1] == self.expected_n_input_joints * 3
        assert prediction.shape[0] == target.shape[0]
        dof = 3

        def _to_rotmat(x):
            b = x.shape[0]
            xaa = aa2rotmat(np.reshape(x, [b, -1, dof]))
            return np.reshape(xaa, [b, -1])

        self.visualize_rotmat(_to_rotmat(seed), _to_rotmat(prediction), _to_rotmat(target), title)

    def visualize_rotmat(self, seed, prediction, target, fname):
        assert seed.shape[-1] == prediction.shape[-1] == target.shape[-1] == self.expected_n_input_joints * 9
        assert prediction.shape[0] == target.shape[0]
        n_joints = self.expected_n_input_joints
        dof = 9

        # stitch seed in front of prediction and target
        pred = np.concatenate([seed, prediction], axis=0)
        targ = np.concatenate([seed, target], axis=0)

        # make sure the rotations are valid
        pred_val = np.reshape(pred, [-1, n_joints, 3, 3])
        pred = get_closest_rotmat(pred_val)
        pred = np.reshape(pred, [-1, n_joints * dof])

        # check that the targets are valid
        targ_are_valid = is_valid_rotmat(np.reshape(targ, [-1, n_joints, 3, 3]))
        assert targ_are_valid, 'target rotation matrices are not valid rotations'

        # check that the targets are valid
        pred_are_valid = is_valid_rotmat(np.reshape(pred, [-1, n_joints, 3, 3]))
        assert pred_are_valid, 'predicted rotation matrices are not valid rotations'

        # calculate positions
        if self.is_sparse:
            pred_pos = self.fk_engine.from_sparse(pred, return_sparse=False)  # (N, full_n_joints, 3)
            targ_pos = self.fk_engine.from_sparse(targ, return_sparse=False)  # (N, full_n_joints, 3)
        else:
            pred_pos = self.fk_engine.from_rotmat(pred)
            targ_pos = self.fk_engine.from_rotmat(targ)

        pred_pos = pred_pos[..., [0, 2, 1]]
        targ_pos = targ_pos[..., [0, 2, 1]]

        fname = fname.replace('/', '.')
        fname = fname.split('_')[0]  # reduce name otherwise stupid OSes (like all of them) can't handle it
        
        out_name, save_to = None, None
        if self.video_dir is not None:
            out_name = os.path.join(self.video_dir, fname, fname + "_skeleton.mp4")
        if self.frames_dir is not None:
            save_to = os.path.join(self.frames_dir, fname, "frames_skeleton/")
        
        visualize_positions(positions=[pred_pos, targ_pos],
                            colors=[_colors[0], _colors[0]],
                            titles=['prediction', 'target'],
                            fig_title=fname,
                            parents=self.fk_engine.parents,
                            change_color_after_frame=(seed.shape[0], None),
                            out_file=out_name,
                            frame_dir=save_to)


def create_mp4_clip(out_path, frame_path_format, fps=60, start_frame=0):
    """Creates an mp4 video clip by using already stored frames in png format.

    Args:
        out_path: <output-file-path>.mp4
        frame_path_format: <path-to-frames>frame_%04d.png
        fps:
        start_frame:
    Returns:
    """
    # create movie and save it to destination
    command = ['ffmpeg',
               '-start_number', str(start_frame),
               '-framerate', str(fps),  # must be this early, otherwise it is not respected
               '-r', '30',  # output is 30 fps
               '-loglevel', 'panic',
               '-i', frame_path_format,
               '-c:v', 'libx264',
               '-preset', 'slow',
               '-profile:v', 'high',
               '-level:v', '4.0',
               '-pix_fmt', 'yuv420p',
               '-y',
               out_path]
    fnull = open(os.devnull, 'w')
    subprocess.Popen(command, stdout=fnull).wait()
    fnull.close()


def visualize_positions(positions, colors, titles, fig_title, parents, change_color_after_frame=None, overlay=False,
                        out_file=None, frame_dir=None, fps=60):
    """
    Visualize motion given 3D positions. Can visualize several motions side by side. If the sequence lengths don't
    match, all animations are displayed until the shortest sequence length.
    Args:
        positions: a list of np arrays in shape (seq_length, n_joints, 3) giving the 3D positions per joint and frame
        colors: list of color for each entry in `positions`
        titles: list of titles for each entry in `positions`
        fig_title: title for the entire figure
        parents: skeleton structure
        out_file: output file path if the visualization is to be saved as video of frames
        fps: frames per second
        change_color_after_frame: after this frame id, the color of the plot is changed (for each entry in `positions`)
        overlay: if true, all entries in `positions` are plotted into the same subplot
        frame_dir: directory to write individual frames. If it is not passed, then a temporary folder is created and
            deleted after creating the clip.
    """
    seq_length = np.amin([pos.shape[0] for pos in positions])
    n_joints = positions[0].shape[1]
    pos = positions

    # create figure with as many subplots as we have skeletons
    fig = plt.figure(figsize=(16, 9))
    plt.clf()
    n_axes = 1 if overlay else len(pos)
    axes = [fig.add_subplot(1, n_axes, i + 1, projection='3d') for i in range(n_axes)]
    fig.suptitle(fig_title)

    # create point object for every bone in every skeleton
    all_lines = []
    # available_colors = ['b', 'r', 'g', 'c', 'm', 'y', 'k', 'w']
    for i, joints in enumerate(pos):
        idx = 0 if overlay else i
        ax = axes[idx]
        lines_j = [
            ax.plot(joints[0:1, n,  0], joints[0:1, n, 1], joints[0:1, n, 2], '-o',
                    markersize=2.0, color=colors[i])[0] for n in range(1, n_joints)]
        all_lines.append(lines_j)
        ax.set_title(titles[i])

    # dirty hack to get equal axes behaviour
    min_val = np.amin(pos[0], axis=(0, 1))
    max_val = np.amax(pos[0], axis=(0, 1))
    max_range = (max_val - min_val).max()
    Xb = 0.5 * max_range * np.mgrid[-1:2:2, -1:2:2, -1:2:2][0].flatten() + 0.5 * (max_val[0] + min_val[0])
    Yb = 0.5 * max_range * np.mgrid[-1:2:2, -1:2:2, -1:2:2][1].flatten() + 0.5 * (max_val[1] + min_val[1])
    Zb = 0.5 * max_range * np.mgrid[-1:2:2, -1:2:2, -1:2:2][2].flatten() + 0.5 * (max_val[2] + min_val[2])

    for ax in axes:
        ax.set_aspect('equal')
        ax.axis('off')

        for xb, yb, zb in zip(Xb, Yb, Zb):
            ax.plot([xb], [yb], [zb], 'w')

        # ax.set_xlabel('X')
        # ax.set_ylabel('Y')
        # ax.set_zlabel('Z')

        ax.set_yticklabels([])
        ax.set_xticklabels([])
        ax.set_zticklabels([])

        ax.xaxis.set_pane_color((1.0, 1.0, 1.0, 0.0))
        ax.yaxis.set_pane_color((1.0, 1.0, 1.0, 0.0))
        ax.zaxis.set_pane_color((0.5, 0.5, 0.5, 0.0))
        # ax.zaxis.set_pane_color((0.5, 0.5, 0.5, 0.5))

        ax.xaxis._axinfo["grid"]['color'] = (1, 1, 1, 0)
        ax.yaxis._axinfo["grid"]['color'] = (1, 1, 1, 0)
        ax.zaxis._axinfo["grid"]['color'] = (1, 1, 1, 0)

        ax.view_init(elev=0, azim=-56)

    def on_move(event):
        # find which axis triggered the event
        source_ax = None
        for i in range(len(axes)):
            if event.inaxes == axes[i]:
                source_ax = i
                break

        # transfer rotation and zoom to all other axes
        if source_ax is None:
            return

        for i in range(len(axes)):
            if i != source_ax:
                axes[i].view_init(elev=axes[source_ax].elev, azim=axes[source_ax].azim)
                axes[i].set_xlim3d(axes[source_ax].get_xlim3d())
                axes[i].set_ylim3d(axes[source_ax].get_ylim3d())
                axes[i].set_zlim3d(axes[source_ax].get_zlim3d())
        fig.canvas.draw_idle()

    c1 = fig.canvas.mpl_connect('motion_notify_event', on_move)
    fig_text = fig.text(0.05, 0.05, '')

    def update_frame(num, positions, lines, parents, colors):
        for l in range(len(positions)):
            k = 0
            pos = positions[l]
            points_j = lines[l]
            for i in range(1, len(parents)):
                a = pos[num, i]
                b = pos[num, parents[i]]
                p = np.vstack([b, a])
                points_j[k].set_data(p[:, :2].T)
                points_j[k].set_3d_properties(p[:, 2].T)
                if change_color_after_frame and change_color_after_frame[l] and num >= change_color_after_frame[l]:
                    points_j[k].set_color(_colors[2])  # use _colors[2] for non-RNN-SPL models
                else:
                    points_j[k].set_color(colors[l])

                k += 1
        time_passed = '{:>.2f} seconds passed'.format(1/60.0*num)
        fig_text.set_text(time_passed)

    # create the animation object, for animation to work reference to this object must be kept
    line_ani = animation.FuncAnimation(fig, update_frame, seq_length,
                                       fargs=(pos, all_lines, parents, colors + [colors[0]]),
                                       interval=1000/fps)
    if out_file is None:
        plt.show()  # interactive
    else:
        assert out_file.endswith('.mp4'), "Only mp4 extension works."
        if frame_dir is None:
            save_to = out_file + "_tmp/"
        else:
            save_to = frame_dir
            
        if not os.path.exists(save_to):
            os.makedirs(save_to)

        # Save frames into disk.
        for j in range(0, seq_length):
            update_frame(j, *[pos, all_lines, parents, colors + [colors[0]]])
            fig.savefig(os.path.join(save_to, 'frame_{:0>4}.{}'.format(j, "png")), dip=1000)
        
        # Create a video clip.
        create_mp4_clip(out_file, os.path.join(save_to, 'frame_%04d.png'))
        # Delete frames if they are not required to store.
        if frame_dir is None:
            shutil.rmtree(save_to)
    plt.close()


def save_animation(fig, seq_length, update_func, update_func_args, out_folder, image_format="png",
                   start_recording=0, end_recording=None, create_mp4=False, fps=60):
    """
    Save animation as transparent pngs to disk.
    Args:
        fig: Figure where animation is displayed.
        seq_length: Total length of the animation.
        update_func: Update function that is driving the animation.
        update_func_args: Arguments for `update_func`.
        out_folder: Where to store the frames.
        image_format: In which format to save the frames.
        start_recording: Frame index where to start recording.
        end_recording: Frame index where to stop recording (defaults to `seq_length`, exclusive).
        create_mp4: Convert frames to a movie using ffmpeg.
        fps: Input and output fps.
    """
    if create_mp4:
        assert image_format == "png"
    tmp_path = out_folder
    if not os.path.exists(tmp_path):
        os.makedirs(tmp_path)

    start_frame = start_recording
    end_frame = end_recording or seq_length

    for j in range(start_frame, end_frame):
        update_func(j, *update_func_args)
        fig.savefig(os.path.join(tmp_path, 'frame_{:0>4}.{}'.format(j, image_format)), dip=1000)

    if create_mp4:
        # create movie and save it to destination
        counter = 0
        movie_name = os.path.join(out_folder, "vid{}.mp4".format(counter))

        while os.path.exists(movie_name):
            counter += 1
            movie_name = os.path.join(out_folder, "vid{}.mp4".format(counter))

        frame_path = os.path.join(out_folder, 'frame_%04d.png')
        create_mp4_clip(movie_name, frame_path, fps)


def visualize_smpl_mesh(vertices, faces, joints, alpha=0.2, show=True, save_to=None, dense=True):

    # flip y and z
    vertices[:, 1], vertices[:, 2] = vertices[:, 2], np.copy(vertices[:, 1])
    joints[:, 1], joints[:, 2] = joints[:, 2], np.copy(joints[:, 1])

    fig = plt.figure(figsize=(16, 9))
    ax = fig.add_subplot(111, projection='3d')

    mesh = Poly3DCollection(vertices[faces], alpha=alpha, linewidths=(0.25,))
    face_color = (141 / 255, 184 / 255, 226 / 255)
    edge_color = (50 / 255, 50 / 255, 50 / 255)
    mesh.set_edgecolor(edge_color)

    # from matplotlib.colors import LightSource
    # from matplotlib import cm
    # ls = LightSource(270, 45)
    # rgb = ls.shade(vertices[:, 2], cmap=cm.gist_earth, vert_exag=0.1, blend_mode='soft')
    mesh.set_facecolor(face_color)
    ax.add_collection3d(mesh)
    for i in range(1, len(SMPL_PARENTS)):
        a = joints[i]
        b = joints[SMPL_PARENTS[i]]
        p = np.vstack([b, a])
        ax.plot(p[:, 0], p[:, 1], p[:, 2], '-o',
                markersize=2.0, color='r')

    # ax.scatter(joints[:, 0], joints[:, 1], joints[:, 2], color='r')

    # dirty hack to get equal axes behaviour
    # min_val = np.amin(vertices, axis=0)
    # max_val = np.amax(vertices, axis=0)
    min_val = np.array([-1.0, -1.0, -1.5])
    max_val = np.array([1.0, 0.5, 0.5])
    max_range = (max_val - min_val).max()
    Xb = 0.5 * max_range * np.mgrid[-1:2:2, -1:2:2, -1:2:2][0].flatten() + 0.5 * (max_val[0] + min_val[0])
    Yb = 0.5 * max_range * np.mgrid[-1:2:2, -1:2:2, -1:2:2][1].flatten() + 0.5 * (max_val[1] + min_val[1])
    Zb = 0.5 * max_range * np.mgrid[-1:2:2, -1:2:2, -1:2:2][2].flatten() + 0.5 * (max_val[2] + min_val[2])

    ax.set_aspect('equal')
    ax.axis('off')

    for xb, yb, zb in zip(Xb, Yb, Zb):
        ax.plot([xb], [yb], [zb], 'w')

    ax.view_init(elev=0, azim=41)

    # cam_equal_aspect_3d(ax, vertices)
    if show:
        plt.show()
    else:
        assert save_to
        fig.savefig(save_to, dip=1000)
    plt.close()


def visualize_quaternet():
    experiment_id = "1553184554"
    is_longterm = True
    results_folder = "C:\\Users\\manuel\\projects\\motion-modelling\\quaternet_results\\test_results_quaternet_{}{}.npz".format(experiment_id,
                                                                                                                                "_longterm" if is_longterm else "")
    d = dict(np.load(results_folder))

    selected_idxs = []
    if not is_longterm:
        selected_labels = ["ACCAD/0/Male1General",
                           "ACCAD/0/Male1Running",
                           "ACCAD/0/Male2MartialArtsStances_c3dD12",
                           "ACCAD/3/Male2General",
                           "BioMotion/0/rub0030023",
                           "BioMotion/1/rub0050003",
                           "BioMotion/2/rub0120028",
                           "BioMotion/4/rub0020002",
                           "BioMotion/4/rub0220000",
                           "BioMotion/5/rub0050000"]
    else:
        selected_labels = ["ACCAD/0/Male1Walking_c3dWalk_SB_B14"]

    for s_label in selected_labels:
        counter = 0
        for idx, label in enumerate(d['labels']):
            if label.startswith(s_label):
                counter += 1
                selected_idxs.append(idx)

        assert counter == 1

    fk_engine = SMPLForwardKinematics()
    video_dir = os.path.join("C:\\Users\\manuel\\projects\\motion-modelling\\quaternet_results\\", experiment_id)
    visualizer = Visualizer(fk_engine, video_dir, rep="quat")

    for idx in selected_idxs:
        visualizer.visualize(d['seed'][idx], d['prediction'][idx], d['target'][idx], title=d['labels'][idx])


if __name__ == '__main__':
    visualize_quaternet()
