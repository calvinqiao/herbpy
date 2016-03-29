PACKAGE = 'herbpy'
import logging
import openravepy
import prpy
import prpy.rave, prpy.util
from prpy.base.barretthand import BarrettHand
from prpy.base.wam import WAM
from prpy.base.robot import Robot
from prpy.exceptions import PrPyException
from prpy.planning.base import UnsupportedPlanningError
from herbbase import HerbBase
from herbpantilt import HERBPantilt

logger = logging.getLogger('herbpy')


def try_and_warn(fn, exception_type, message, default_value=None):
    try:
        return fn()
    except exception_type:
        logger.warning(message)
        return None


class HERBRobot(Robot):
    def __init__(self, left_arm_sim, right_arm_sim, right_ft_sim,
                       left_hand_sim, right_hand_sim, left_ft_sim,
                       head_sim, talker_sim, segway_sim, perception_sim):
        from prpy.util import FindCatkinResource

        Robot.__init__(self, robot_name='herb')

        # Convenience attributes for accessing self components.
        self.left_arm = self.GetManipulator('left')
        self.right_arm = self.GetManipulator('right')
        self.head = self.GetManipulator('head')
        self.left_arm.hand = self.left_arm.GetEndEffector()
        self.right_arm.hand = self.right_arm.GetEndEffector()
        self.left_hand = self.left_arm.hand
        self.right_hand = self.right_arm.hand
        self.manipulators = [ self.left_arm, self.right_arm, self.head ]

        # Dynamically switch to self-specific subclasses.
        prpy.bind_subclass(self.left_arm, WAM, sim=left_arm_sim, owd_namespace='/left/owd')
        prpy.bind_subclass(self.right_arm, WAM, sim=right_arm_sim, owd_namespace='/right/owd')
        prpy.bind_subclass(self.head, HERBPantilt, sim=head_sim, owd_namespace='/head/owd')
        prpy.bind_subclass(self.left_arm.hand, BarrettHand, sim=left_hand_sim, manipulator=self.left_arm,
                           owd_namespace='/left/owd', bhd_namespace='/left/bhd', ft_sim=right_ft_sim)
        prpy.bind_subclass(self.right_arm.hand, BarrettHand, sim=right_hand_sim, manipulator=self.right_arm,
                           owd_namespace='/right/owd', bhd_namespace='/right/bhd', ft_sim=right_ft_sim)
        self.base = HerbBase(sim=segway_sim, robot=self)

        # Set HERB's acceleration limits. These are not specified in URDF.
        accel_limits = self.GetDOFAccelerationLimits()
        accel_limits[self.head.GetArmIndices()] = [ 2. ] * self.head.GetArmDOF()
        accel_limits[self.left_arm.GetArmIndices()] = [ 2. ] * self.left_arm.GetArmDOF()
        accel_limits[self.right_arm.GetArmIndices()] = [ 2. ] * self.right_arm.GetArmDOF()
        self.SetDOFAccelerationLimits(accel_limits)
        
        # Support for named configurations.
        import os.path
        self.configurations.add_group('left_arm', self.left_arm.GetArmIndices())
        self.configurations.add_group('right_arm', self.right_arm.GetArmIndices())
        self.configurations.add_group('head', self.head.GetArmIndices())
        self.configurations.add_group('left_hand', self.left_hand.GetIndices())
        self.configurations.add_group('right_hand', self.right_hand.GetIndices())

        configurations_path = FindCatkinResource('herbpy', 'config/configurations.yaml')
        
        try:
            self.configurations.load_yaml(configurations_path)
        except IOError as e:
            raise ValueError('Failed laoding named configurations from "{:s}".'.format(
                configurations_path))

        # Hand configurations
        from prpy.named_config import ConfigurationLibrary
        for hand in [ self.left_hand, self.right_hand ]:
            hand.configurations = ConfigurationLibrary()
            hand.configurations.add_group('hand', hand.GetIndices())
            
            if isinstance(hand, BarrettHand):
                hand_configs_path = FindCatkinResource('herbpy', 'config/barrett_preshapes.yaml')
                try:
                    hand.configurations.load_yaml(hand_configs_path)
                except IOError as e:
                    raise ValueError('Failed loading named hand configurations from "{:s}".'.format(
                        hand_configs_path))
            else:
                logger.warn('Unrecognized hand class. Not loading named configurations.')
        
        # Initialize a default planning pipeline.
        from prpy.planning import (
            FirstSupported,
            MethodMask,
            Ranked,
            Sequence,
        )
        from prpy.planning import (
            CBiRRTPlanner,
            CHOMPPlanner,
            GreedyIKPlanner,
            IKPlanner,
            NamedPlanner,
            SBPLPlanner,
            SnapPlanner,
            TSRPlanner,
            VectorFieldPlanner
        )

        # TODO: These should be meta-planners.
        self.named_planner = NamedPlanner()
        self.ik_planner = IKPlanner()

        # Special-purpose planners.
        self.snap_planner = SnapPlanner()
        self.vectorfield_planner = VectorFieldPlanner()
        self.greedyik_planner = GreedyIKPlanner()

        # General-purpose planners.
        self.cbirrt_planner = CBiRRTPlanner()

        # Trajectory optimizer.
        try:
            from or_trajopt import TrajoptPlanner
            self.trajopt_planner = TrajoptPlanner()  
        except ImportError:
            self.trajopt_planner = None
            logger.warning('Failed creating TrajoptPlanner. Is the or_trajopt'
                           ' package in your workspace and built?')

        try:
            self.chomp_planner = CHOMPPlanner()
        except UnsupportedPlanningError:
            self.chomp_planner = None
            logger.warning('Failed loading the CHOMP module. Is the or_cdchomp'
                           ' package in your workspace and built?')

        if not (self.trajopt_planner or self.chomp_planner):
            raise PrPyException('Unable to load both CHOMP and TrajOpt. At'
                                ' least one of these packages is required.')
        
        actual_planner = Sequence(
            # First, try the straight-line trajectory.
            self.snap_planner,
            # Then, try a few simple (and fast!) heuristics.
            self.vectorfield_planner,
            #self.greedyik_planner,
            # Next, try a trajectory optimizer.
            self.trajopt_planner or self.chomp_planner
        )
        self.planner = FirstSupported(
            Sequence(actual_planner, 
                     TSRPlanner(delegate_planner=actual_planner),
                     self.cbirrt_planner),
            # Special purpose meta-planner.
            NamedPlanner(delegate_planner=actual_planner),
        )
        
        from prpy.planning.retimer import HauserParabolicSmoother
        self.smoother = HauserParabolicSmoother(do_blend=True, do_shortcut=True)
        self.retimer = HauserParabolicSmoother(do_blend=True, do_shortcut=False,
            blend_iterations=5, blend_radius=0.4)
        self.simplifier = None

        # Base planning
        from prpy.util import FindCatkinResource
        planner_parameters_path = FindCatkinResource('herbpy', 'config/base_planner_parameters.yaml')

        self.sbpl_planner = SBPLPlanner()
        try:
            with open(planner_parameters_path, 'rb') as config_file:
                import yaml
                params_yaml = yaml.load(config_file)
            self.sbpl_planner.SetPlannerParameters(params_yaml)
        except IOError as e:
            raise ValueError('Failed loading base planner parameters from "{:s}".'.format(
                planner_parameters_path))

        self.base_planner = self.sbpl_planner

        # Create action library
        from prpy.action import ActionLibrary
        self.actions = ActionLibrary()

        # Register default actions and TSRs
        import herbpy.action
        import herbpy.tsr


        # Setting necessary sim flags
        self.talker_simulated = talker_sim
        self.segway_sim = segway_sim

        # Set up perception
        self.detector=None
        if perception_sim:
            from prpy.perception import SimulatedPerceptionModule
            self.detector = SimulatedPerceptionModule()
        else:
            from prpy.perception import ApriltagsModule
            try:
                kinbody_path = prpy.util.FindCatkinResource('pr_ordata',
                                                            'data/objects')
                marker_data_path = prpy.util.FindCatkinResource('pr_ordata',
                                                                'data/objects/tag_data.json')
                self.detector = ApriltagsModule(marker_topic='/apriltags_kinect2/marker_array',
                                                marker_data_path=marker_data_path,
                                                kinbody_path=kinbody_path,
                                                detection_frame='head/kinect2_rgb_optical_frame',
                                                destination_frame='herb_base',
                                                reference_link=self.GetLink('/herb_base'))
            except IOError as e:
                 logger.warning('Failed to find required resource path. ' \
                                'pr-ordata package cannot be found. ' \
                                'Perception detector will not be loaded.')

        if not self.talker_simulated:
            # Initialize herbpy ROS Node
            import rospy
            if not rospy.core.is_initialized():
                rospy.init_node('herbpy', anonymous=True)
                logger.debug('Started ROS node with name "%s".', rospy.get_name())

            import talker.msg
            from actionlib import SimpleActionClient
            self._say_action_client = SimpleActionClient('say', talker.msg.SayAction)


    def CloneBindings(self, parent):
        from prpy import Cloned
        super(HERBRobot, self).CloneBindings(parent)
        self.left_arm = Cloned(parent.left_arm)
        self.right_arm = Cloned(parent.right_arm)
        self.head = Cloned(parent.head)
        self.left_arm.hand = Cloned(parent.left_arm.GetEndEffector())
        self.right_arm.hand = Cloned(parent.right_arm.GetEndEffector())
        self.left_hand = self.left_arm.hand
        self.right_hand = self.right_arm.hand
        self.manipulators = [ self.left_arm, self.right_arm, self.head ]
        self.planner = parent.planner
        self.base_planner = parent.base_planner

    def ExecuteTrajectory(self, traj, *args, **kwargs):
        from prpy.exceptions import TrajectoryAborted

        active_manipulators = self.GetTrajectoryManipulators(traj)

        for manipulator in active_manipulators:
            manipulator.ClearTrajectoryStatus()

        value = super(HERBRobot, self).ExecuteTrajectory(traj, *args, **kwargs)

        for manipulator in active_manipulators:
            status = manipulator.GetTrajectoryStatus()
            if status == 'aborted':
                raise TrajectoryAborted()

        return value

    # Inherit docstring from the parent class.
    ExecuteTrajectory.__doc__ = Robot.ExecuteTrajectory.__doc__

    def SetStiffness(self, stiffness):
        """Set the stiffness of HERB's arms and head.
        Zero is gravity compensation, one is position control. Stifness values
        between zero and one are experimental.
        @param stiffness value between zero and one
        """
        self.head.SetStiffness(stiffness)
        self.left_arm.SetStiffness(stiffness)
        self.right_arm.SetStiffness(stiffness)
        
    def DetectHuman(self, env, orhuman='kin2_or', load_hum=True,                           
                    enable_legs=True, segway_sim=True, 
                    base_frame='/map' , kin_frame='/head/skel_depth_frame2',
                    hrc=False, herb_sim=True, 
                    continuous=True, action='stamp'):
        """
        Use the data coming from the kinect in order to add a human 
        in the simulation environment. The parameters herb_sim, 
        continuous and action have to be set only if hrc=True.
        
        @param env simulation environment
        @param orhuman equal to kin1_skel, if the data are coming from the kinect1 
                        and a skeleton is used to visualize the human
                       equal kin1_or, if the data are coming from the kinect1 
                        and the openrave human is used for visualization 
                       equal kin2_or, if the data are coming from the kinect2
                        and the openrave human is used for visualization 
        @param load_hum equal to True if the human is loaded in the simulated env
        @param enable_legs equal to False if the legs of the human cannot be tracked,
                           e.g. the legs are covered by a table     
        @param segway_sim equal to False if Herb localization is needed        
        @param hrc equal to True, if the package hrc is used
        @param herb_sim equal to True, if herb is simulated
        @param continuous equal to True, if human precition on goal is continuous.
                          equal to False, if human prediction stops when a certain 
                          threshold is reached.
        @param action if hrc=True, the kind of action the herb is going to perform 
                      between stamping ('stamp') and grasping ('grasp')
        """
        
        
        import rospy
        from tf import TransformListener, transformations

        if orhuman=='kin1_skel': 
            if load_hum==True:
                #kin 1 - load a skeleton
                import or_skeletons.load_skeletons as sk
                humans = []
                logger.info('Humans_tracking')
        elif orhuman=='kin1_or':
            if load_hum==True:
                #kin 1- load the human from openrave
                import humanpy.humantracking_kinect1 as sk
                humans = []
                logger.info('Humans_tracking')
        elif orhuman=='kin2_or':
            if load_hum==True:
                #kin 2 - load the human from openrave
                import humanpy.humantracking_kinect2 as sk
                humans = []
                logger.info('Humans_tracking')
            if hrc==True:
                from hrc import assistance                 
                humans_hrc = []
                logger.info('HRC')
        else:
            raise Exception('orhuman param is not correct')
           
        try:  
            tf = TransformListener()  
            humanadded = False

            while not rospy.is_shutdown():   
                if load_hum==True:
                    sk.addRemoveHumans(tf, humans, env,
                                       enable_legs=enable_legs,
                                       segway_sim=segway_sim,
                                       base_frame=base_frame,
                                       kin_frame=kin_frame)
                    for human in humans:
                        human.update(tf, 1)       
                if hrc==True:
                    if humanadded==False:
                        humanadded = assistance.addHumansPred(tf, humans_hrc, env,
                                                                continuous=continuous,
                                                                herb_sim=herb_sim,
                                                                segway_sim=segway_sim,
                                                                action=action)
                    for human in humans_hrc:
                        human.update(tf)                          
      
        except Exception, e:  #rospy.exceptions.ROSException:
            logger.error('Detection failed update: %s' % str(e))
            raise
        
    def Say(self, words, block=True):
        """Speak 'words' using talker action service or espeak locally in simulation"""
        if self.talker_simulated:
            import subprocess
            try:
                proc = subprocess.Popen(['espeak', '-s', '160', '"{0}"'.format(words)])
                if block:
                    proc.wait()
            except OSError as e:
                logger.error('Unable to speak. Make sure "espeak" is installed locally.\n%s' % str(e))
        else:
            import talker.msg
            goal = talker.msg.SayGoal(text=words)
            self._say_action_client.send_goal(goal)
            if block:
                self._say_action_client.wait_for_result()
