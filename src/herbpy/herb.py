import logging, prpy, prpy.dependency_manager, os
from openravepy import (
    Environment,
    RaveCreateModule,
    RaveInitialize,
)
from .herbbase import HerbBase

logger = logging.getLogger('herbpy')

def initialize(robot_xml=None, env_path=None, attach_viewer=False,
               sim=True, **kw_args):
    import prpy, os

    prpy.logger.initialize_logging()

    # Hide TrajOpt logging.
    os.environ.setdefault('TRAJOPT_LOG_THRESH', 'WARN')

    # Load plugins.
    prpy.dependency_manager.export()
    RaveInitialize(True)

    # Create the environment.
    env = Environment()
    if env_path is not None:
        if not env.Load(env_path):
            raise Exception('Unable to load environment frompath %s' % env_path)

    if prpy.dependency_manager.is_catkin():

        # Load the URDF file into OpenRAVE.
        urdf_module = RaveCreateModule(env, 'urdf')
        if urdf_module is None:
            logger.error('Unable to load or_urdf module. Do you have or_urdf'
                         ' built and installed in one of your Catkin workspaces?')
            raise ValueError('Unable to load or_urdf plugin.')

        urdf_uri = 'package://herb_description/robots/herb.urdf'
        srdf_uri = 'package://herb_description/robots/herb.srdf'
        args = 'Load {:s} {:s}'.format(urdf_uri, srdf_uri)
        herb_name = urdf_module.SendCommand(args)
        if herb_name is None:
            raise ValueError('Failed loading HERB model using or_urdf.')

        robot = env.GetRobot(herb_name)
        if robot is None:
            raise ValueError('Unable to find robot with name "{:s}".'.format(
                             herb_name))
    else:
        if robot_xml is None:
            import os, rospkg
            rospack = rospkg.RosPack()
            base_path = rospack.get_path('herb_description')
            robot_xml = os.path.join(base_path, 'ordata', 'robots', 'herb.robot.xml')

        robot = env.ReadRobotXMLFile(robot_xml)
        env.Add(robot)

    # Default arguments.
    keys = [ 'left_arm_sim', 'left_hand_sim', 'left_ft_sim',
             'right_arm_sim', 'right_hand_sim', 'right_ft_sim',
             'head_sim', 'talker_sim', 'segway_sim', 'perception_sim' ]
    for key in keys:
        if key not in kw_args:
            kw_args[key] = sim

    from herbrobot import HERBRobot
    prpy.bind_subclass(robot, HERBRobot, **kw_args)

    if sim:
        dof_indices, dof_values \
            = robot.configurations.get_configuration('relaxed_home')
        robot.SetDOFValues(dof_values, dof_indices)

    # Start by attempting to load or_rviz.
    if attach_viewer == True:
        attach_viewer = 'rviz'
        env.SetViewer(attach_viewer)

        # Fall back on qtcoin if loading or_rviz failed
        if env.GetViewer() is None:
            logger.warning(
                'Loading the RViz viewer failed. Do you have or_interactive'
                ' marker installed? Falling back on qtcoin.')
            attach_viewer = 'qtcoin'

    if attach_viewer and env.GetViewer() is None:
        env.SetViewer(attach_viewer)
        if env.GetViewer() is None:
            raise Exception('Failed creating viewer of type "{0:s}".'.format(
                            attach_viewer))

    # Remove the ROS logging handler again. It might have been added when we
    # loaded or_rviz.
    prpy.logger.remove_ros_logger()

    return env, robot
