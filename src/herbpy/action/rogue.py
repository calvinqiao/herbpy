import logging, openravepy, prpy 
from prpy.action import ActionMethod
from prpy.util import FindCatkinResource, GetPointFrom
import numpy, time

logger = logging.getLogger('herbpy')

@ActionMethod
def PointAt(robot, focus, manip=None, render=False):
    """
    @param robot The robot performing the point
    @param focus The 3-D coordinate in space or object 
                 that is being pointed at
    @param manip The manipulator to perform the point with. 
                 This must be the right arm
    @param render Render tsr samples during planning
    """
    pointing_coord = GetPointFrom(focus)
    return Point(robot, pointing_coord, manip, render)

@ActionMethod
def PresentAt(robot, focus, manip=None, render=True):
    """
    @param robot The robot performing the presentation
    @param focus The 3-D coordinate in space or object that 
                 is being presented
    @param manip The manipulator to perform the presentation with. 
                 This must be the right arm.
    @param render Render tsr samples during planning
    """
    presenting_coord = GetPointFrom(focus)
    return Present(robot, presenting_coord, manip, render)

@ActionMethod
def SweepAt(robot, start, end, manip=None, margin=0.3, render=True):
    """
    @param robot The robot performing the sweep
    @param start The object or 3-d position that marks the start
    @param end The object of 3-d position that marks the end
    @param manip The manipulator to perform the sweep
    @param margin The distance between the start object and the hand,
                  so the vertical space between the hand and objects. 
                  This must be enough to clear the objects themselves.
    @param render Render tsr samples during planning
    """
    start_coord = GetPointFrom(start)
    end_coord = GetPointFrom(end)
    return Sweep(robot, start_coord, end_coord, manip, margin, render)

def Point(robot, coord, manip=None, render=False):
    """
    @param robot The robot performing the point
    @param focus The 3-D coordinate in space that is being pointed at
    @param manip The manipulator to perform the point with. 
                 This must be the right arm
    @param render Render tsr samples during planning
    """
    if manip is None:
        manip = robot.GetActiveManipulator()

    if manip.GetName() != 'right':
        raise prpy.exceptions.PrPyException('Pointing is only defined'
                ' on the right arm.')

    focus_trans = numpy.eye(4, dtype='float')
    focus_trans[0:3, 3] = coord

    with robot.GetEnv():
        point_tsr = robot.tsrlibrary(None, 'point', focus_trans, manip)

    p = openravepy.KinBody.SaveParameters
    with robot.CreateRobotStateSaver(p.ActiveManipulator | p.ActiveDOF):
        robot.SetActiveManipulator(manip)
        robot.SetActiveDOFs(manip.GetArmIndices())
        with prpy.viz.RenderTSRList(point_tsr, robot.GetEnv(), render=render):
            robot.PlanToTSR(point_tsr, execute=True)
    manip.hand.MoveHand(f1=2.4, f2=0.8, f3=2.4, spread=3.14)

def Present(robot, coord, manip=None, render=True):
    """
    @param robot The robot performing the presentation
    @param focus The 3-D coordinate in space or object that 
                 is being presented
    @param manip The manipulator to perform the presentation with. 
                 This must be the right arm.
    @param render Render tsr samples during planning
    """
    if manip is None:
        manip = robot.GetActiveManipulator()

    if manip.GetName() != 'right':
        raise prpy.exceptions.PrPyException('Presenting is only defined'
                ' on the right arm.')

    focus_trans = numpy.eye(4, dtype='float')
    focus_trans[0:3, 3] = coord

    with robot.GetEnv():
        present_tsr = robot.tsrlibrary(None, 'present', focus_trans, manip)
    
    p = openravepy.KinBody.SaveParameters
    with robot.CreateRobotStateSaver(p.ActiveManipulator | p.ActiveDOF):
        robot.SetActiveManipulator(manip)
        robot.SetActiveDOFs(manip.GetArmIndices())
        with prpy.viz.RenderTSRList(present_tsr, robot.GetEnv(), render=render):
            robot.PlanToTSR(present_tsr, execute=True)
    manip.hand.MoveHand(f1=1, f2=1, f3=1, spread=3.14)


def Sweep(robot, start_coords, end_coords, manip=None, margin=0.3, render=True):
    """
    @param robot The robot performing the sweep
    @param start The object or 3-d position that marks the start
    @param end The object of 3-d position that marks the end
    @param manip The manipulator to perform the sweep
    @param margin The distance between the start object and the hand,
                  so the vertical space between the hand and objects. 
                  This must be enough to clear the objects themselves.
    @param render Render tsr samples during planning
    """
    if manip is None:
        manip = robot.GetActiveManipulator()

    #ee_offset : such that the hand, not wrist, is above the object
    #hand_pose : places the hand above the start location
    if manip.GetName() == 'right':
        hand = robot.right_hand
        ee_offset = -0.2
        hand_pose = numpy.array([[ 0, -1, 0, start_coords[0]],
                                 [ 0,  0, 1, (start_coords[1]+ee_offset)],
                                 [-1,  0, 0, (start_coords[2]+margin)],
                                 [ 0,  0, 0, 1]], dtype='float')

    elif manip.GetName() == 'left':
        hand = robot.left_hand
        ee_offset = 0.2
        hand_pose = numpy.array([[ 0, 1, 0, start_coords[0]],
                                 [ 0, 0, -1, (start_coords[1]+ee_offset)],
                                 [-1, 0, 0, (start_coords[2]+margin)],
                                 [ 0, 0, 0, 1]], dtype='float')
  
    else:
        raise prpy.exceptions.PrPyException('Manipulator does not have an'
                 ' associated hand')

    end_trans = numpy.eye(4, dtype='float')
    end_trans[0:3, 3] = end_coords

    hand.MoveHand(f1=1, f2=1, f3=1, spread=3.14)
    q = openravepy.KinBody.SaveParameters
    with robot.CreateRobotStateSaver(q.ActiveManipulator | q.ActiveDOF):
        robot.SetActiveManipulator(manip)
        robot.SetActiveDOFs(manip.GetArmIndices())
        manip.PlanToEndEffectorPose(hand_pose, execute=True)

    #TSR to sweep to end position
    with robot.GetEnv():
        sweep_tsr = robot.tsrlibrary(None, 'sweep', end_trans, manip)

    p = openravepy.KinBody.SaveParameters
    with robot.CreateRobotStateSaver(p.ActiveManipulator | p.ActiveDOF):
        robot.SetActiveManipulator(manip)
        robot.SetActiveDOFs(manip.GetArmIndices())
        with prpy.viz.RenderTSRList(sweep_tsr, robot.GetEnv(), render=render):
            robot.PlanToTSR(sweep_tsr, execute=True)

@ActionMethod
def Exhibit(robot, obj, manip=None, distance=0.1, wait=2, release=True, render=True):
    """
    @param robot The robot performing the exhibit
    @param obj The object being exhibited
    @param manip The maniplator to perform the exhibit
    @param distance The distance the object will be lifted up
    @param wait The amount of time the object will be held up in seconds
    @param render Render tsr samples during planning
    """

    with robot.GetEnv():
        if manip is None:
            manip = robot.GetActiveManipulator()
        preconfig = manip.GetDOFValues()
    robot.Grasp(obj)

    p = openravepy.KinBody.SaveParameters
    with robot.CreateRobotStateSaver(p.ActiveManipulator | p.ActiveDOF):
        robot.SetActiveManipulator(manip)
        robot.SetActiveDOFs(manip.GetArmIndices())    
        
        #Lift the object
        lift_tsr = robot.tsrlibrary(obj, 'lift', manip, distance=distance)
        with prpy.viz.RenderTSRList(lift_tsr, robot.GetEnv(), render=render):
            robot.PlanToTSR(lift_tsr, execute=True)

        #Wait for 'time'
        time.sleep(wait)

        #'Unlift' the object, so place it back down
        unlift_tsr = robot.tsrlibrary(obj, 'lift', manip, distance=-distance)
        with prpy.viz.RenderTSRList(unlift_tsr, robot.GetEnv(), render=render):
            robot.PlanToTSR(unlift_tsr, execute=True)

    if release:
        with robot.GetEnv():
            robot.Release(obj)
        manip.hand.OpenHand()
        manip.PlanToConfiguration(preconfig)

@ActionMethod
def NodYes(robot):
    """
    @param robot The robot being used to nod
    """
    pause = 0.15
    inc = 4

    for i in xrange(inc):
        robot.head.Servo([0, 1])
        time.sleep(pause)
    for i in xrange((inc*3)):
        robot.head.Servo([0, -1])
        time.sleep(pause)
    for i in xrange((inc*2)):
        robot.head.Servo([0, 1])
        time.sleep(pause)

@ActionMethod
def NodNo(robot):
    """
    @param robot The robot being used to nod
    """
    pause = 0.15
    inc = 4

    for i in xrange(inc):
        robot.head.Servo([1, 0])
        time.sleep(pause)
    for i in xrange((inc*3)):
        robot.head.Servo([-1, 0])
        time.sleep(pause)
    for i in xrange((inc*2)):
        robot.head.Servo([1, 0])
        time.sleep(pause)

@ActionMethod
def HaltHand(robot, manip=None):
    """
    @param robot The robot being used for the stopping gesture
    @param manip The manipulator being used for the stopping gesture
    """

    if manip == None:
        manip = robot.GetActiveManipulator()

    if manip.GetName() == 'right':
        pose = numpy.array([5.03348748, -1.57569674,  1.68788069,
                            2.06769058, -1.66834313,
                            1.53679821,  0.21175342], dtype='float')
        
        manip.PlanToConfiguration(pose, execute=True)
        robot.right_hand.MoveHand(f1=0, f2=0, f3=0, spread=3.14)
    elif manip.GetName() == 'left':
        pose = numpy.array([ 1.30614268, -1.76      , -1.57063853,
                             2.07228362,  1.23918377,
                             1.46215605, -0.12918424], dtype='float')

        manip.PlanToConfiguration(pose, execute=True)
        robot.left_hand.MoveHand(f1=0, f2=0, f3=0, spread=3.14)
    else: 
        raise prpy.exceptions.PrPyException(
            'HaltHand is only defined for the left and right arm.')

@ActionMethod
def MiddleFinger(robot, manip=None):
    """
    @param robot The robot being used to give the middle finger
    @param manip The manipulator being used to give the middle finger.
                 Must be either the right or left arm.
    """
    if manip is None:
        manip = robot.GetActiveManipulator()

    if manip.GetName() == 'right':
        right_dof = numpy.array([ 5.03348748, -1.57569674,  1.68788069,  
                                  2.06769058, -1.66834313,
                                  1.53679821,  0.21175342], dtype='float')
         
        manip.PlanToConfiguration(right_dof, execute=True)
        robot.right_hand.MoveHand(f1=2, f2=2, f3=0, spread=3.14)

    elif manip.GetName() == 'left':
        left_dof = numpy.array([ 1.30614268, -1.76      , -1.57063853,  
                                 2.07228362,  1.23918377,
                                 1.46215605, -0.12918424], dtype='float')

        manip.PlanToConfiguration(left_dof, execute=True)
        robot.left_hand.MoveHand(f1=2, f2=2, f3=0, spread=3.14)
    else: 
        raise prpy.exceptions.PrPyException('The middle finger is only defined'
                                ' for the left and right arm.')


@ActionMethod
def Wave(robot):
    """
    @param robot The robot waving with their right arm
    """

    from prpy.rave import load_trajectory
    from os.path import join
    env = robot.GetEnv()

    wave_path = FindCatkinResource('herbpy', 'config/waveTrajs/')
    traj0 = load_trajectory(env, join(wave_path, 'wave0.xml'))
    traj1 = load_trajectory(env, join(wave_path, 'wave1.xml'))
    traj2 = load_trajectory(env, join(wave_path, 'wave2.xml'))
    traj3 = load_trajectory(env, join(wave_path, 'wave3.xml'))

    manip = robot.right_arm
    robot.HaltHand(manip=manip)
    robot.ExecuteTrajectory(traj0)
    robot.ExecuteTrajectory(traj1)
    robot.ExecuteTrajectory(traj2)
    robot.ExecuteTrajectory(traj3)
